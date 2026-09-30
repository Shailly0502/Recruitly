"""Plain-English search.

Only used on Enter, when the input doesn't parse or is plain words matching
nobody. Jev routes -> DeepSeek translates -> parser validates (one retry)
-> describe -> Jev checks -> run, or suggest if unsure. Falls back to the
normal search if a model fails. Only the typed text is sent, never candidates.
"""

from dataclasses import dataclass
from datetime import datetime

from ..search import QueryError, SearchResult, parser, run
from ..search.parser import And, Name, Not, Or
from ..store import Candidate
from . import AI, deepseek, jev, messages, questions
from .describe import describe

DIRECT = "direct"                    # no AI needed, or none available
INTERPRETED = "interpreted"          # translated, checked, and run
SUGGESTION = "suggestion"            # low confidence: offered, not run
OFF_TOPIC = "off_topic"
UNCLEAR = "unclear"
TYPO = "query_typo"                  # show the parser error
NAME = "candidate_name"              # show the name search
UNINTERPRETABLE = "uninterpretable"  # no valid query came back
FALLBACK = "fallback"                # a model failed or timed out


@dataclass
class Outcome:
    path: str
    message: str | None = None
    query: str | None = None         # query run or suggested
    description: str | None = None
    confidence: float | None = None  # Jev's translation_ok probability
    result: SearchResult | None = None
    error: QueryError | None = None  # parser error for the raw input


def assist(ai: AI, text: str, candidates: list[Candidate], now: datetime) -> Outcome:
    tree, result, error = None, None, None
    try:
        tree = parser.parse(text, now)
        result = run(tree, candidates, now)
    except QueryError as parse_error:
        error = parse_error
    plain = Outcome(DIRECT, result=result, error=error)

    if not ai.enabled or not (error or _plain_words_matching_nobody(tree, result)):
        return plain
    try:
        return _with_ai(ai, text, candidates, now, plain)
    except (jev.JevError, deepseek.DeepSeekError):
        return Outcome(FALLBACK, result=result, error=error)


def _plain_words_matching_nobody(tree, result: SearchResult) -> bool:
    """Two or more bare words matching nobody, e.g. "who got hired last week".
    "or"/"and"/"not" in a sentence parse as operators but still count."""
    words = list(_leaves(tree))
    return len(words) >= 2 and all(isinstance(word, Name) and ":" not in word.src for word in words) \
        and not result.matches


def _leaves(node):
    if isinstance(node, (And, Or)):
        for child in node.children:
            yield from _leaves(child)
    elif isinstance(node, Not):
        yield from _leaves(node.child)
    else:
        yield node


def _with_ai(ai: AI, text: str, candidates: list[Candidate], now: datetime, plain: Outcome) -> Outcome:
    routed = jev.route(ai.jev, text)
    if routed.on_topic < questions.ON_TOPIC_THRESHOLD or routed.kind == OFF_TOPIC:
        return Outcome(OFF_TOPIC, message=messages.OFF_TOPIC)
    if routed.kind == UNCLEAR:
        return Outcome(UNCLEAR, message=messages.UNCLEAR)
    if routed.kind != "english_question":
        return Outcome(routed.kind, result=plain.result, error=plain.error)

    could_not = Outcome(UNINTERPRETABLE, message=messages.COULD_NOT_INTERPRET, result=plain.result, error=plain.error)
    query = deepseek.translate(ai.deepseek, text, now)
    if query == deepseek.UNSUPPORTED:
        return could_not
    tree = _parse(query, now)
    if isinstance(tree, QueryError):
        query = deepseek.translate(ai.deepseek, text, now, failed=(query, tree.message))
        tree = _parse(query, now)
        if isinstance(tree, QueryError):
            return could_not

    description = describe(tree, now)
    confidence = jev.translation_ok(ai.jev, text, description)
    if confidence < questions.TRANSLATION_OK_THRESHOLD:
        return Outcome(SUGGESTION, message=messages.LOW_CONFIDENCE, query=query, description=description,
                       confidence=confidence)
    return Outcome(INTERPRETED, message=messages.INTERPRETED.format(description=description), query=query,
                   description=description, confidence=confidence, result=run(tree, candidates, now))


def _parse(query: str, now: datetime):
    if not query or query == deepseek.UNSUPPORTED:
        return QueryError("No query was produced.")
    try:
        return parser.parse(query, now)
    except QueryError as error:
        return error
