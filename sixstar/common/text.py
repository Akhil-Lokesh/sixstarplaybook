"""Cleaning, normalizing and slugging questions."""
from __future__ import annotations

import hashlib
import re
import unicodedata

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_SPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^a-z0-9 ]+")

# Common ways players write the game's name, folded so cache keys match.
_ALIASES = [
    (re.compile(r"\bgta\s*(vi|6)\b"), "gta 6"),
    (re.compile(r"\bgrand theft auto\s*(vi|6)\b"), "gta 6"),
]


def clean_question(raw: str, max_chars: int) -> str:
    """Trimming whitespace and control characters; the result is what the model sees."""
    text = unicodedata.normalize("NFKC", raw or "")
    text = _CONTROL.sub(" ", text)
    text = _SPACE.sub(" ", text).strip()
    return text[:max_chars].strip()


def normalize_question(question: str) -> str:
    """Folding a question to a canonical form for the answer cache key."""
    text = question.lower()
    text = text.replace("'", "").replace("’", "")
    for pattern, repl in _ALIASES:
        text = pattern.sub(repl, text)
    text = _NON_WORD.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def question_hash(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def slugify(text: str, max_len: int = 72) -> str:
    slug = _NON_WORD.sub(" ", text.lower())
    slug = _SPACE.sub("-", slug.strip())
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0]
    return slug or "question"
