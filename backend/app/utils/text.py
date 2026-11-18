from __future__ import annotations

import re
import unicodedata

_WORD = re.compile(r"[a-z0-9']+")
STOPWORDS = frozenset(
    """a an the and or but if then so of to in on at by for with from as is are was were be been being it its
    this that these those i you he she we they them his her our their my your me us not no do does did done
    have has had can could should would will just very really about into over than also there here what which
    who whom how why when where all any some more most such only own same too s t don now get got like""".split()
)


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s']", " ", text)
    return normalize_ws(text)


def tokens(text: str, *, drop_stopwords: bool = True) -> list[str]:
    toks = _WORD.findall(normalize_for_match(text))
    if drop_stopwords:
        toks = [t for t in toks if t not in STOPWORDS and len(t) > 1]
    return toks


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token for English)."""
    return max(1, len(text) // 4)
