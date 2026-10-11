"""
core/indexing.py — extraction du texte page par page et vignette de la 1re page.

Utilisé par la commande index_documents et, à la volée, par l'endpoint thumbnail.
"""
import html
import io
import logging
import os
import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Document, DocumentPage, SearchTerm
from .r2 import get_r2_client
from .text import clean_lines, extract_words

logger = logging.getLogger(__name__)

PDF_EXT = {'.pdf'}
IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}
TEXT_EXT = {'.txt', '.py', '.r', '.md', '.csv', '.sql', '.tex', '.html', '.htm', '.json', '.do', '.sas'}

MAX_BYTES = 80 * 1024 * 1024        # au-delà, on n'indexe pas (mémoire du conteneur)
MAX_TEXT_BYTES = 2 * 1024 * 1024
THUMB_WIDTH = 360
TAG_RE = re.compile(r"<[^>]+>")


def file_ext(doc) -> str:
    return os.path.splitext(doc.file_name or doc.file_path or '')[1].lower()


def thumbnail_key_for(doc) -> str:
    return f"{settings.CF_R2_THUMBS_PREFIX}/{doc.id}.png"


def can_thumbnail(doc) -> bool:
    return not doc.is_folder and file_ext(doc) in PDF_EXT | IMAGE_EXT


def _download(client, key):
    head = client.head_object(Bucket=settings.CF_R2_BUCKET_NAME, Key=key)
    if head['ContentLength'] > MAX_BYTES:
        raise ValueError(f"fichier trop lourd ({head['ContentLength']} octets)")
    obj = client.get_object(Bucket=settings.CF_R2_BUCKET_NAME, Key=key)
    return obj['Body'].read()


def _render_thumbnail(pdoc) -> bytes:
    import pymupdf
    page = pdoc[0]
    zoom = THUMB_WIDTH / max(page.rect.width, 1)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return pix.tobytes("png")


def _upload_thumbnail(client, doc, png: bytes) -> str:
    key = thumbnail_key_for(doc)
    client.put_object(
        Bucket=settings.CF_R2_BUCKET_NAME, Key=key, Body=png,
        ContentType='image/png', CacheControl='public, max-age=604800',
    )
    return key


def _text_pages(ext: str, data: bytes):
    text = data[:MAX_TEXT_BYTES].decode('utf-8', errors='replace')
    if ext in {'.html', '.htm'}:
        text = html.unescape(TAG_RE.sub('\n', text))
    return [text]


def _save_pages(doc, pages):
    """Remplace les pages indexées du document et enrichit le vocabulaire."""
    rows, words = [], set()
    for i, text in enumerate(pages, start=1):
        lines = clean_lines(text)
        if not lines:
            continue
        content = "\n".join(lines)
        rows.append(DocumentPage(document=doc, page_number=i, content=content))
        words |= extract_words(content)
    with transaction.atomic():
        DocumentPage.objects.filter(document=doc).delete()
        DocumentPage.objects.bulk_create(rows, batch_size=200)
    if words:
        SearchTerm.objects.bulk_create(
            [SearchTerm(word=w) for w in words], ignore_conflicts=True, batch_size=1000,
        )
    return len(rows)


def index_document(doc: Document, client=None, with_text: bool = True) -> str:
    """
    Indexe un document : texte des pages (si with_text) + vignette de la 1re page.
    Retourne un court statut pour le journal. Marque indexed_at seulement si
    with_text, pour qu'une vignette générée à la volée n'empêche pas l'indexation.
    """
    import pymupdf

    client = client or get_r2_client()
    ext = file_ext(doc)
    status = 'ignoré'

    try:
        if doc.is_folder:
            status = 'dossier'
        elif ext in PDF_EXT or ext in IMAGE_EXT:
            data = _download(client, doc.file_path)
            filetype = 'pdf' if ext in PDF_EXT else ext.lstrip('.')
            with pymupdf.open(stream=io.BytesIO(data), filetype=filetype) as pdoc:
                if pdoc.page_count:
                    doc.thumbnail_key = _upload_thumbnail(client, doc, _render_thumbnail(pdoc))
                if ext in PDF_EXT:
                    doc.page_count = pdoc.page_count
                    if with_text:
                        n = _save_pages(doc, [p.get_text("text") for p in pdoc])
                        status = f'pdf {pdoc.page_count} p., {n} avec texte'
                    else:
                        status = 'vignette'
                else:
                    doc.page_count = 1
                    status = 'image'
        elif ext in TEXT_EXT and with_text:
            data = _download(client, doc.file_path)
            n = _save_pages(doc, _text_pages(ext, data))
            doc.page_count = 1
            status = f'texte ({n} p.)'
    except Exception as exc:  # un fichier illisible ne doit pas bloquer les autres
        logger.warning("Indexation %s (%s) impossible : %s", doc.id, doc.file_path, exc)
        status = f'erreur : {exc}'

    fields = {'page_count': doc.page_count, 'thumbnail_key': doc.thumbnail_key}
    if with_text:
        doc.indexed_at = fields['indexed_at'] = timezone.now()
    Document.objects.filter(pk=doc.pk).update(**fields)
    return status
