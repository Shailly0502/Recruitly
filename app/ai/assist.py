"""Plain-English search.

Only used on Enter, when the words typed in the search box match no candidate's
name. Jev routes -> DeepSeek translates -> parser validates (one retry) ->
converted to portal filters (anything no menu can hold is kept as "advanced")
-> described -> Jev checks -> run, or suggested if unsure. Falls back to the name search if a model fails. Only the typed text is
sent, never candidates.
"""

from dataclasses import dataclass, replace
from datetime import datetime

from ..search import FilterError, Filters, QueryError, SearchResult, parser
from ..search import filters as portal_filters
from ..search.describe import describe
from ..store import Candidate
from . import AI, deepseek, jev, messages, questions

DIRECT = "direct"                    # no AI needed, or none available
INTERPRETED = "interpreted"          # translated, checked, and run
SUGGESTION = "suggestion"            # low confidence: offered, not run
OFF_TOPIC = "off_topic"
UNCLEAR = "unclear"
NAME = "candidate_name"              # show the name search
UNINTERPRETABLE = "uninterpretable"  # no valid query came back
FALLBACK = "fallback"                # a model failed or timed out


@dataclass
class Outcome:
    path: str
    message: str | None = None
    filters: Filters | None = None   # filters run or suggested
    query: str | None = None         # DeepSeek's query behind them, for the evals
    description: str | None = None
    confidence: float | None = None  # Jev's translation_ok probability
    result: SearchResult | None = None
    ran: Filters | None = None       # the filters `result` came from
    error: FilterError | None = None  # why the typed name search can't run


def assist(ai: AI, text: str, current: Filters, candidates: list[Candidate], now: datetime) -> Outcome:
    """`text` is what was typed in the search box; `current` the filters already applied."""
    result, error, typed = None, None, replace(current, name=text)
    try:
        result = portal_filters.search(typed, candidates, now)
    except FilterError as filter_error:
        error = filter_error
    plain = Outcome(DIRECT, result=result, ran=typed if result else None, error=error)

    if not ai.enabled or not text.strip() or _names_someone(text, candidates, now):
        return plain
    try:
        return _with_ai(ai, text, candidates, now, plain)
    except (jev.JevError, deepseek.DeepSeekError):
        return Outcome(FALLBACK, result=plain.result, ran=plain.ran, error=error)


def _names_someone(text: str, candidates: list[Candidate], now: datetime) -> bool:
    """Whether the typed words, as a name search on their own, find anyone."""
    try:
        return bool(portal_filters.search(Filters(name=text), candidates, now).matches)
    except FilterError:
        return False


def _with_ai(ai: AI, text: str, candidates: list[Candidate], now: datetime, plain: Outcome) -> Outcome:
    routed = jev.route(ai.jev, text)
    if routed.on_topic < questions.ON_TOPIC_THRESHOLD or routed.kind == OFF_TOPIC:
        return Outcome(OFF_TOPIC, message=messages.OFF_TOPIC)
    if routed.kind == UNCLEAR:
        return Outcome(UNCLEAR, message=messages.UNCLEAR)
    if routed.kind != "english_question":
        return Outcome(routed.kind, result=plain.result, ran=plain.ran, error=plain.error)

    could_not = Outcome(UNINTERPRETABLE, message=messages.COULD_NOT_INTERPRET, result=plain.result, ran=plain.ran,
                        error=plain.error)
    query = deepseek.translate(ai.deepseek, text, now)
    if query == deepseek.UNSUPPORTED:
        return could_not
    found = _filters(query, now)
    if isinstance(found, str):
        query = deepseek.translate(ai.deepseek, text, now, failed=(query, found))
        found = _filters(query, now)
        if isinstance(found, str):
            return could_not

    # Describe the filters that will actually run, not the raw query.
    description = describe(portal_filters.to_tree(found, now), now)
    confidence = jev.translation_ok(ai.jev, text, description)
    if confidence < questions.TRANSLATION_OK_THRESHOLD:
        return Outcome(SUGGESTION, message=messages.LOW_CONFIDENCE, filters=found, query=query,
                       description=description, confidence=confidence)
    return Outcome(INTERPRETED, message=messages.INTERPRETED.format(description=description), filters=found,
                   query=query, description=description, confidence=confidence,
                   result=portal_filters.search(found, candidates, now), ran=found)


def _filters(query: str, now: datetime) -> Filters | str:
    """The portal filters for DeepSeek's query, or why there are none."""
    if not query or query == deepseek.UNSUPPORTED:
        return "No query was produced."
    try:
        tree = parser.parse(query, now)
    except QueryError as error:
        return error.message
    found = portal_filters.from_tree(tree, now)
    try:
        portal_filters.to_tree(found, now)
    except FilterError as error:
        return error.message
    return found
