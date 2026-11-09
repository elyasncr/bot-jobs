"""Text normalization helpers shared by filters, dedupe and models."""

import hashlib
import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_text(text: str) -> str:
    """Lowercase, strip accents and collapse whitespace."""
    return _WHITESPACE.sub(" ", strip_accents(text).lower()).strip()


def make_fingerprint(title: str, company: str) -> str:
    """sha1(normalize(title) + normalize(company)) — identifies the same job across sources."""
    key = f"{normalize_text(title)}|{normalize_text(company)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()
