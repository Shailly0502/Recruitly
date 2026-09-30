"""Tokens -> query tree, or a QueryError explaining what's wrong.

Grammar (a space between terms means AND):

    query  := and ( OR and )*
    and    := unary+
    unary  := "-" unary | NOT unary | "(" query ")" | term
    term   := word                      a name, typos allowed
            | stage:STAGE               current stage
            | for:[op]DURATION          time in current stage, e.g. for:>7d
            | reached:STAGE[op DATE]    entered a stage, e.g. reached:interview>=monday
            | job:ID                    the job applied for, e.g. job:JOB-001
            | name:WORD                 a name that looks like a keyword
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .. import jobs, stages
from . import lexer
from .fuzzy import suggest
from .lexer import QueryError, Token

FIELDS = ["stage", "for", "reached", "job", "name"]
OPERATORS = [">=", "<=", ">", "<", "="]

UNIT_SECONDS = {
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "wk": 604800, "wks": 604800, "week": 604800, "weeks": 604800,
}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DURATION_HELP = "Use a number and a unit, like 12h, 7d or 2w."
DATE_HELP = "Use a weekday (monday), today, yesterday, a date (2026-09-28) or how long ago (3d)."


@dataclass(frozen=True)
class Node:
    src: str  # source text, for explanations
    pos: int  # offset of src


@dataclass(frozen=True)
class Name(Node):
    term: str


@dataclass(frozen=True)
class StageIs(Node):
    stage: str


@dataclass(frozen=True)
class InStageFor(Node):
    op: str
    seconds: float


@dataclass(frozen=True)
class Reached(Node):
    stage: str
    op: str | None = None        # None: reached at any time
    start: datetime | None = None
    end: datetime | None = None  # the day (or moment) named


@dataclass(frozen=True)
class JobIs(Node):
    job_id: str


@dataclass(frozen=True)
class Not(Node):
    child: Node


@dataclass(frozen=True)
class And(Node):
    children: tuple[Node, ...]


@dataclass(frozen=True)
class Or(Node):
    children: tuple[Node, ...]


def parse(query: str, now: datetime) -> Node:
    """`now` is the recruiter's local time, used for "monday", "today", etc."""
    tokens = lexer.tokenize(query)
    if not tokens:
        raise QueryError("Type a name or a filter, like stage:interview.", 0)
    return _Parser(query, tokens, now).parse()


class _Parser:
    def __init__(self, query: str, tokens: list[Token], now: datetime):
        self.query = query
        self.tokens = tokens
        self.now = now
        self.i = 0

    def parse(self) -> Node:
        node = self._or()
        if self._peek() is not None:  # only a stray ")" can stop _or early
            raise QueryError("This ')' has no matching '('.", self._peek().start)
        return node

    def _peek(self) -> Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _next(self) -> Token:
        token = self.tokens[self.i]
        self.i += 1
        return token

    def _src(self, start: int) -> tuple[str, int]:
        return self.query[start:self.tokens[self.i - 1].end], start

    def _or(self) -> Node:
        start = self._position()
        children = [self._and()]
        while self._peek() is not None and self._peek().kind == lexer.OR:
            self._next()
            children.append(self._and())
        return children[0] if len(children) == 1 else Or(*self._src(start), tuple(children))

    def _and(self) -> Node:
        start = self._position()
        children: list[Node] = []
        while self._peek() is not None and self._peek().kind not in (lexer.RPAREN, lexer.OR):
            if self._peek().kind == lexer.AND:
                token = self._next()
                following = self._peek()
                if not children or following is None or following.kind in (lexer.RPAREN, lexer.OR, lexer.AND):
                    raise QueryError("AND needs something on both sides.", token.start)
                continue
            children.append(self._unary())
        if not children:
            self._fail_empty()
        self._check_one_stage(children)
        return children[0] if len(children) == 1 else And(*self._src(start), tuple(children))

    def _unary(self) -> Node:
        token = self._next()
        if token.kind == lexer.NOT:
            following = self._peek()
            if following is None or following.kind in (lexer.RPAREN, lexer.OR, lexer.AND):
                raise QueryError(f"'{token.text}' must be followed by what to exclude, like -stage:rejected.",
                                 token.start)
            child = self._unary()
            return Not(*self._src(token.start), child)
        if token.kind == lexer.LPAREN:
            if self._peek() is not None and self._peek().kind == lexer.RPAREN:
                raise QueryError("These parentheses are empty.", token.start)
            node = self._or()
            if self._peek() is None:
                raise QueryError("This '(' is never closed. Add a ')'.", token.start)
            self._next()
            return node
        if token.kind == lexer.PHRASE:
            return self._phrase(token)
        return self._term(token)

    def _position(self) -> int:
        token = self._peek()
        return token.start if token else len(self.query)

    def _fail_empty(self):
        token = self._peek()
        previous = self.tokens[self.i - 1] if self.i else None
        if token is not None and token.kind == lexer.OR:
            raise QueryError("OR needs something on both sides, like stage:interview OR stage:offer.", token.start)
        if previous is not None and previous.kind == lexer.OR:
            raise QueryError("OR needs something on both sides, like stage:interview OR stage:offer.", previous.start)
        raise QueryError("This ')' has no matching '('.", token.start if token else 0)

    def _check_one_stage(self, children: list[Node]):
        current = [child for child in children if isinstance(child, StageIs)]
        for other in current[1:]:
            if other.stage != current[0].stage:
                raise QueryError(
                    f"A candidate is only ever in one stage, so '{current[0].src} {other.src}' can't match anyone. "
                    f"Did you mean '{current[0].src} OR {other.src}'?",
                    other.pos,
                )

    def _phrase(self, token: Token) -> Node:
        words = token.text.split()
        if not words:
            raise QueryError("These quotes are empty.", token.start)
        names = tuple(Name(word, token.start, word) for word in words)
        return names[0] if len(names) == 1 else And(self.query[token.start:token.end], token.start, names)

    def _term(self, token: Token) -> Node:
        text, start = token.text, token.start
        if text[0] in "<>=":
            raise QueryError(
                f"'{text}' isn't attached to a filter. Write it without spaces, like reached:interview>=monday.",
                start,
            )
        if ":" not in text:
            if any(ch in text for ch in "<>="):
                raise QueryError(
                    f"'{text}' compares something but doesn't say what. "
                    "Start with a field, like reached:interview>=monday or for:>7d.",
                    start,
                )
            return Name(text, start, text)

        field, value = text.split(":", 1)
        field = field.lower()
        value_start = start + len(field) + 1
        if field not in FIELDS:
            hint = suggest(field, FIELDS)
            if hint:
                raise QueryError(f"'{field}' isn't a field. Did you mean '{hint}'?", start)
            raise QueryError(f"'{field}' isn't a field. The fields are {', '.join(FIELDS)}.", start)
        if not value:
            examples = {"stage": "stage:interview", "for": "for:>7d", "reached": "reached:offer", "job": "job:JOB-001",
                        "name": "name:priya"}
            raise QueryError(f"'{field}:' needs a value, like {examples[field]}.", start)

        if field == "name":
            return Name(text, start, value)
        if field == "job":
            return JobIs(text, start, jobs.normalize_id(value))
        if field == "stage":
            return StageIs(text, start, self._stage(value, value_start))
        if field == "for":
            return self._for(text, start, value, value_start)
        return self._reached(text, start, value, value_start)

    def _stage(self, value: str, position: int) -> str:
        value = value.lower()
        if value in stages.ALL_STAGES:
            return value
        # Accept unique prefixes like stage:int.
        starts = [stage for stage in stages.ALL_STAGES if stage.startswith(value)]
        if len(starts) == 1:
            return starts[0]
        hint = suggest(value, stages.ALL_STAGES)
        if hint:
            raise QueryError(f"'{value}' isn't a stage. Did you mean '{hint}'?", position)
        raise QueryError(f"'{value}' isn't a stage. The stages are {', '.join(stages.ALL_STAGES)}.", position)

    def _for(self, src: str, pos: int, value: str, position: int) -> Node:
        op, rest = _split_operator(value)
        if op == "=":
            raise QueryError("Time in a stage is never exact. Use > or <, like for:>7d.", position)
        if not rest:
            raise QueryError(f"'for:{value}' is missing a duration. {DURATION_HELP}", position)
        seconds = _duration(rest)
        if seconds is None:
            raise QueryError(f"'{rest}' isn't a duration. {DURATION_HELP}", position + len(value) - len(rest))
        return InStageFor(src, pos, op or ">=", seconds)

    def _reached(self, src: str, pos: int, value: str, position: int) -> Node:
        found = [value.index(op) for op in OPERATORS if op in value]
        if found:
            stage_text = value[:min(found)]
            op, when_text = _split_operator(value[min(found):])
        else:
            stage_text, op, when_text = value, None, ""
        if not stage_text:
            raise QueryError("'reached:' needs a stage first, like reached:interview>=monday.", position)
        stage = self._stage(stage_text, position)
        if op is None:
            return Reached(src, pos, stage)

        when_position = position + len(value) - len(when_text)
        if not when_text:
            raise QueryError(f"'{op}' needs a date after it. {DATE_HELP}", when_position)
        start, end = self._when(when_text.lower(), when_position)
        if op == "=" and start == end:
            raise QueryError(f"'{when_text}' is a moment, not a day. Use >= or <, like reached:{stage}>={when_text}.",
                             when_position)
        return Reached(src, pos, stage, op, start, end)

    def _when(self, text: str, position: int) -> tuple[datetime, datetime]:
        """Time span for `text`: a whole day, or a single moment for "3d"."""
        today = self.now.replace(hour=0, minute=0, second=0, microsecond=0)
        day = None
        if text == "today":
            day = today
        elif text == "yesterday":
            day = today - timedelta(days=1)
        else:
            weekdays = [name for name in WEEKDAYS if name == text or (len(text) >= 3 and name.startswith(text))]
            if len(weekdays) == 1:
                # The most recent one, counting today.
                day = today - timedelta(days=(today.weekday() - WEEKDAYS.index(weekdays[0])) % 7)
            elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                try:
                    day = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=self.now.tzinfo)
                except ValueError:
                    raise QueryError(f"'{text}' isn't a real date.", position) from None
        if day is not None:
            return day, day + timedelta(days=1)

        seconds = _duration(text)
        if seconds is not None:
            moment = self.now - timedelta(seconds=seconds)
            return moment, moment
        hint = suggest(text, WEEKDAYS + ["today", "yesterday"])
        if hint:
            raise QueryError(f"'{text}' isn't a date. Did you mean '{hint}'?", position)
        raise QueryError(f"'{text}' isn't a date. {DATE_HELP}", position)


def _split_operator(text: str) -> tuple[str | None, str]:
    for op in OPERATORS:
        if text.startswith(op):
            return op, text[len(op):]
    return None, text


def _duration(text: str) -> float | None:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([a-z]+)", text.lower())
    if not match or match.group(2) not in UNIT_SECONDS:
        return None
    return float(match.group(1)) * UNIT_SECONDS[match.group(2)]
