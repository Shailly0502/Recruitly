"""Typo-tolerant matching for names and for "did you mean" suggestions."""

import re


def distance(a: str, b: str) -> int:
    """Optimal string alignment distance: an adjacent swap is one edit ("sharam" -> "sharma" = 1)."""
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        row = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            row[j] = min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                row[j] = min(row[j], prev2[j - 2] + 1)
        prev2, prev = prev, row
    return prev[len(b)]


def allowed_typos(term: str) -> int:
    """Short words must match exactly, or everything matches."""
    if len(term) <= 3:
        return 0
    if len(term) <= 7:
        return 1
    return 2


def name_tokens(name: str) -> list[str]:
    return [token for token in re.split(r"[^\w]+", name.lower()) if token]


def word_score(term: str, token: str) -> float:
    """Typed word vs one word of a name: 0 (no match) to 1 (exact)."""
    if term == token:
        return 1.0
    if token.startswith(term):
        return 0.8 + 0.1 * len(term) / len(token)
    typos = allowed_typos(term)
    if typos == 0:
        return 0.0
    d = distance(term, token)
    if d <= typos:
        return 0.7 - 0.15 * (d - 1)
    # Partial word with a typo, e.g. "shra" while typing "sharma".
    if len(token) > len(term) and distance(term, token[: len(term)]) <= 1:
        return 0.4
    return 0.0


def name_score(term: str, name: str) -> float:
    """Best match against any word of the name."""
    term = term.lower()
    return max((word_score(term, token) for token in name_tokens(name)), default=0.0)


def suggest(word: str, options: list[str]) -> str | None:
    """Closest option, if it's close enough to be a typo."""
    word = word.lower()
    best = min(options, key=lambda option: distance(word, option), default=None)
    if best is not None and distance(word, best) <= max(1, len(best) // 3):
        return best
    return None
