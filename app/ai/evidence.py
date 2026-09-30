"""Keeps an extracted fact only if its quote is actually in the resume."""

import re
from dataclasses import dataclass, field
from datetime import date

_PUNCTUATION = {
    0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"',  # curly quotes
    0x2013: "-", 0x2014: "-",                            # en and em dashes
    0x00A0: " ",                                         # non-breaking space
}


@dataclass
class Verified:
    skills: list[dict] = field(default_factory=list)      # name, quote
    roles: list[dict] = field(default_factory=list)       # title, organization, start, end, quote
    experience: dict | None = None                        # years, quote
    dropped: list[dict] = field(default_factory=list)     # facts whose quote wasn't found

    def to_dict(self) -> dict:
        return {"skills": self.skills, "roles": self.roles, "experience": self.experience, "dropped": self.dropped}


def normalize(text: str) -> str:
    """Ignore case, whitespace and curly quotes when comparing quotes."""
    return re.sub(r"\s+", " ", text.translate(_PUNCTUATION)).strip().lower()


def verify(facts: dict, resume_text: str) -> Verified:
    haystack = normalize(resume_text)

    def quoted(item) -> bool:
        quote = item.get("quote") if isinstance(item, dict) else None
        return isinstance(quote, str) and len(quote.strip()) >= 3 and normalize(quote) in haystack

    result = Verified()
    seen = set()
    for skill in _list(facts.get("skills")):
        name = _text(skill, "name")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        if quoted(skill):
            result.skills.append({"name": name, "quote": skill["quote"].strip()})
        else:
            result.dropped.append({"kind": "skill", "label": name})

    for role in _list(facts.get("roles")):
        title = _text(role, "title")
        if not title:
            continue
        if quoted(role):
            result.roles.append({
                "title": title,
                "organization": _text(role, "organization"),
                "start": _text(role, "start"),
                "end": _text(role, "end"),
                "quote": role["quote"].strip(),
            })
        else:
            result.dropped.append({"kind": "role", "label": title})

    experience = facts.get("experience")
    if isinstance(experience, dict) and isinstance(experience.get("years"), (int, float)) \
            and not isinstance(experience.get("years"), bool):
        if quoted(experience):
            result.experience = {"years": float(experience["years"]), "quote": experience["quote"].strip()}
        else:
            result.dropped.append({"kind": "experience", "label": f"{experience['years']} years"})
    return result


def years_from_roles(roles: list[dict], today: date) -> float | None:
    """Years covered by the role dates, overlaps counted once."""
    spans = []
    for role in roles:
        start = _month(role.get("start"), today)
        end = _month(role.get("end"), today)
        if start is not None and end is not None and end >= start:
            spans.append((start, end))
    if not spans:
        return None
    spans.sort()
    months, (current_start, current_end) = 0, spans[0]
    for start, end in spans[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            months += current_end - current_start
            current_start, current_end = start, end
    months += current_end - current_start
    return round(months / 12, 1)


def _month(value, today: date) -> int | None:
    """Date as a month count, or None if unreadable."""
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if value in ("present", "current", "now"):
        return today.year * 12 + today.month - 1
    match = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?", value)
    if not match or not 1 <= int(match.group(2) or 1) <= 12:
        return None
    return int(match.group(1)) * 12 + int(match.group(2) or 1) - 1


def _list(value) -> list:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(item: dict, key: str) -> str | None:
    value = item.get(key)
    return value.strip()[:120] if isinstance(value, str) and value.strip() else None
