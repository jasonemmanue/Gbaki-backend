"""
core/text.py — normalisation de texte commune à la recherche et à l'indexation.
"""
import re
import unicodedata

WORD_RE = re.compile(r"[a-z0-9]{3,40}")


def normalize_text(text):
    """Minuscules, sans accents, espaces en bord retirés."""
    if not text:
        return ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def clean_lines(text):
    """Lignes non vides, espaces compactés. Le numéro de ligne affiché = index + 1."""
    lines = []
    # PostgreSQL refuse le caractère NUL, présent dans certains PDF
    for raw in (text or "").replace("\x00", "").splitlines():
        line = " ".join(raw.split())
        if line:
            lines.append(line)
    return lines


def extract_words(text):
    """Mots normalisés (3 à 40 caractères, au moins une lettre) d'un texte."""
    return {w for w in WORD_RE.findall(normalize_text(text)) if not w.isdigit()}
