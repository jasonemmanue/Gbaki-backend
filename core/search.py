"""
core/search.py — recherche plein texte dans les pages indexées (DocumentPage).

PostgreSQL : index GIN sur to_tsvector('french', gbaki_unaccent(content)) (migration 0009)
et correction des fautes via le vocabulaire SearchTerm (trigrammes).
SQLite (dev/tests) : repli sur icontains, sans correction.

Chaque page trouvée est ensuite découpée en lignes pour donner le numéro de ligne,
l'extrait, le type de correspondance (exacte / proche) et les plages à surligner.
"""
import re
from dataclasses import dataclass, field

from django.db import connection

from .models import Document, DocumentPage, SearchTerm
from .text import normalize_text

STOPWORDS = {
    'le', 'la', 'les', 'de', 'des', 'du', 'un', 'une', 'et', 'ou', 'en', 'au', 'aux',
    'a', 'l', 'd', 'que', 'qui', 'quoi', 'est', 'sur', 'pour', 'par', 'dans', 'avec',
    'ce', 'cet', 'cette', 'ces', 'se', 'sa', 'son', 'ses', 'il', 'elle', 'on', 'ne', 'pas',
}
TOKEN_RE = re.compile(r"[a-z0-9]+")
MAX_PAGES = 60
MAX_HITS_PER_PAGE = 3
MAX_HITS = 100


@dataclass
class ParsedQuery:
    raw: str
    phrase: str                       # requête normalisée (espaces compactés)
    terms: list                       # termes saisis, normalisés, sans mots vides
    effective: list                   # termes après correction orthographique
    corrections: dict = field(default_factory=dict)   # terme saisi -> mot du vocabulaire

    def stem(self, term):
        return term[:max(4, len(term) - 2)] if len(term) > 4 else term


# ── Analyse de la requête ────────────────────────────────────────────────────

def _closest_term(term: str):
    """Mot du vocabulaire le plus proche (pg_trgm), ou None."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT word FROM core_searchterm WHERE word %% %s "
            "ORDER BY similarity(word, %s) DESC, length(word) LIMIT 1",
            [term, term],
        )
        row = cur.fetchone()
    return row[0] if row else None


def parse_query(raw: str) -> ParsedQuery:
    phrase = " ".join(normalize_text(raw).split())
    terms = [t for t in TOKEN_RE.findall(phrase) if len(t) >= 2 and t not in STOPWORDS]
    corrections = {}
    if connection.vendor == 'postgresql':
        known = set(SearchTerm.objects.filter(word__in=terms).values_list('word', flat=True))
        for t in terms:
            if len(t) >= 4 and t not in known and not t.isdigit():
                best = _closest_term(t)
                if best and best != t:
                    corrections[t] = best
    effective = [corrections.get(t, t) for t in terms]
    return ParsedQuery(raw=raw, phrase=phrase, terms=terms, effective=effective, corrections=corrections)


# ── Pages candidates ─────────────────────────────────────────────────────────

def _candidate_pages_pg(q: ParsedQuery, class_id, operator: str):
    tsq = f" {operator} ".join(["plainto_tsquery('french', gbaki_unaccent(%s))"] * len(q.effective))
    params = list(q.effective)
    class_sql = ""
    if class_id:
        class_sql = "AND d.class_id_id = %s"
        params.append(str(class_id))
    params.append(MAX_PAGES)
    sql = f"""
        SELECT p.document_id, p.page_number, p.content
        FROM core_documentpage p
        JOIN core_document d ON d.id = p.document_id,
             (SELECT {tsq} AS q) AS qq
        WHERE d.is_published
          AND to_tsvector('french', gbaki_unaccent(p.content)) @@ qq.q
          {class_sql}
        ORDER BY ts_rank(to_tsvector('french', gbaki_unaccent(p.content)), qq.q) DESC,
                 p.page_number
        LIMIT %s
    """
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return [(str(doc_id), int(page), content) for doc_id, page, content in cur.fetchall()]


def _candidate_pages_fallback(q: ParsedQuery, class_id):
    qs = DocumentPage.objects.filter(document__is_published=True)
    if class_id:
        qs = qs.filter(document__class_id=class_id)
    for t in q.effective:
        qs = qs.filter(content__icontains=q.stem(t))
    return [(str(p.document_id), p.page_number, p.content) for p in qs[:MAX_PAGES]]


def candidate_pages(q: ParsedQuery, class_id=None):
    if not q.effective:
        return []
    if connection.vendor != 'postgresql':
        return _candidate_pages_fallback(q, class_id)
    pages = _candidate_pages_pg(q, class_id, '&&')
    if len(pages) < 5 and len(q.effective) > 1:
        seen = {(d, n) for d, n, _ in pages}
        pages += [p for p in _candidate_pages_pg(q, class_id, '||') if (p[0], p[1]) not in seen]
    return pages[:MAX_PAGES]


# ── Analyse ligne par ligne ──────────────────────────────────────────────────

def normalize_with_map(line: str):
    """Texte normalisé + index du caractère d'origine pour chaque caractère normalisé."""
    chars, mapping = [], []
    for i, ch in enumerate(line):
        for n in normalize_text(ch) if not ch.isspace() else ' ':
            chars.append(n)
            mapping.append(i)
    return "".join(chars), mapping


def _span(mapping, start, end, line_len):
    s = mapping[start] if start < len(mapping) else line_len
    e = mapping[end - 1] + 1 if end - 1 < len(mapping) else line_len
    return [s, e]


def analyse_line(line: str, q: ParsedQuery):
    """
    Retourne None ou {'kind', 'spans', 'found'} pour une ligne.
    exacte : la requête complète apparaît telle quelle (accents et casse ignorés).
    proche : au moins la moitié des termes (ou leur racine / leur correction) apparaissent.
    """
    norm, mapping = normalize_with_map(line)
    if q.phrase and len(q.phrase) >= 2:
        idx = norm.find(q.phrase)
        if idx >= 0:
            spans = []
            while idx >= 0:
                spans.append(_span(mapping, idx, idx + len(q.phrase), len(line)))
                idx = norm.find(q.phrase, idx + len(q.phrase))
            return {'kind': 'exact', 'spans': spans, 'found': None}

    spans, matched, found = [], 0, None
    for typed, term in zip(q.terms, q.effective):
        hits = list(re.finditer(r"\b" + re.escape(q.stem(term)) + r"[a-z0-9]*", norm))
        if not hits:
            continue
        matched += 1
        for m in hits:
            spans.append(_span(mapping, m.start(), m.end(), len(line)))
        word = hits[0].group(0)
        if found is None and word != typed:
            found = {'word': line[spans[-len(hits)][0]:spans[-len(hits)][1]], 'for': typed}
    needed = max(1, (len(q.terms) + 1) // 2)
    if matched >= needed:
        spans.sort()
        return {'kind': 'close', 'spans': spans, 'found': found}
    return None


def page_lines(content: str, q: ParsedQuery = None):
    lines = content.split("\n")
    out = []
    for i, line in enumerate(lines, start=1):
        info = analyse_line(line, q) if q and q.terms else None
        out.append({'n': i, 'text': line, 'spans': info['spans'] if info else []})
    return out


# ── Point d'entrée ───────────────────────────────────────────────────────────

def search_fulltext(raw: str, class_id=None):
    q = parse_query(raw)
    hits = []
    for doc_id, page_number, content in candidate_pages(q, class_id):
        page_hits = []
        for i, line in enumerate(content.split("\n"), start=1):
            info = analyse_line(line, q)
            if info:
                page_hits.append({
                    'document_id': doc_id, 'page': page_number, 'line': i, 'text': line,
                    'kind': info['kind'], 'spans': info['spans'], 'found': info['found'],
                })
        page_hits.sort(key=lambda h: h['kind'] != 'exact')
        hits.extend(page_hits[:MAX_HITS_PER_PAGE])

    hits.sort(key=lambda h: h['kind'] != 'exact')   # tri stable : garde le rang FTS
    hits = hits[:MAX_HITS]

    doc_ids = {h['document_id'] for h in hits}
    docs = {
        str(d.id): {
            'id': str(d.id), 'title': d.title, 'mime_type': d.mime_type,
            'page_count': d.page_count,
            'subject': d.subject_id.name if d.subject_id else None,
            'document_type': d.document_type_id.label if d.document_type_id else None,
            'academic_year': d.academic_year_id.label if d.academic_year_id else None,
            'class_code': d.class_id.code if d.class_id else None,
        }
        for d in Document.objects.filter(id__in=doc_ids).select_related(
            'subject_id', 'document_type_id', 'academic_year_id', 'class_id')
    }
    return {
        'query': raw,
        'terms': q.terms,
        'corrections': [{'from': k, 'to': v} for k, v in q.corrections.items()],
        'count': len(hits),
        'exact_count': sum(h['kind'] == 'exact' for h in hits),
        'close_count': sum(h['kind'] == 'close' for h in hits),
        'documents_count': len(doc_ids),
        'documents': docs,
        'results': hits,
    }
