"""Runs a query tree over the candidates: filter, rank, and explain empty results."""

from dataclasses import dataclass
from datetime import datetime

from .. import stages
from ..store import Candidate
from . import parser
from .describe import phrase, singular
from .fuzzy import name_score, suggest
from .parser import And, InStageFor, JobIs, Name, Node, Not, Or, Reached, StageIs


@dataclass
class Match:
    candidate: Candidate
    score: float | None  # name similarity 0..1, None if no name searched


@dataclass
class SearchResult:
    matches: list[Match]
    explanation: str | None = None  # why nothing matched


def search(query: str, candidates: list[Candidate], now: datetime) -> SearchResult:
    """Raises QueryError if the query can't be understood."""
    return run(parser.parse(query, now), candidates, now)


def run(tree: Node, candidates: list[Candidate], now: datetime) -> SearchResult:
    matches = []
    for candidate in candidates:
        matched, score = _evaluate(tree, candidate, now)
        if matched:
            matches.append(Match(candidate, score))
    if not matches:
        return SearchResult([], _explain_empty(tree, candidates, now))
    matches.sort(key=_ranking(tree, now))
    return SearchResult(matches)


def _evaluate(node: Node, candidate: Candidate, now: datetime) -> tuple[bool, float | None]:
    """Whether the candidate matches, and how closely their name does."""
    if isinstance(node, Name):
        score = name_score(node.term, candidate.name)
        return score > 0, score
    if isinstance(node, StageIs):
        return candidate.stage == node.stage, None
    if isinstance(node, InStageFor):
        return _compare(candidate.seconds_in_stage(now), node.op, node.seconds), None
    if isinstance(node, Reached):
        return _reached(node, candidate), None
    if isinstance(node, JobIs):
        return candidate.job_id == node.job_id, None
    if isinstance(node, Not):
        return not _evaluate(node.child, candidate, now)[0], None
    results = [_evaluate(child, candidate, now) for child in node.children]
    if isinstance(node, And):
        scores = [score for _, score in results if score is not None]
        return all(matched for matched, _ in results), sum(scores) / len(scores) if scores else None
    scores = [score for matched, score in results if matched and score is not None]
    return any(matched for matched, _ in results), max(scores, default=None)


def _compare(value: float, op: str, limit: float) -> bool:
    return {">": value > limit, ">=": value >= limit, "<": value < limit, "<=": value <= limit}[op]


def _reached(node: Reached, candidate: Candidate) -> bool:
    at = candidate.reached_at(node.stage)
    if at is None:
        return False
    if node.op is None:
        return True
    # start..end is a whole day, so "> monday" means after Monday ends.
    return {
        ">=": at >= node.start,
        ">": at >= node.end if node.end > node.start else at > node.start,
        "<": at < node.start,
        "<=": at < node.end if node.end > node.start else at <= node.start,
        "=": node.start <= at < node.end,
    }[node.op]


def _walk(node: Node, negated: bool = False):
    yield node, negated
    if isinstance(node, Not):
        yield from _walk(node.child, not negated)
    elif isinstance(node, (And, Or)):
        for child in node.children:
            yield from _walk(child, negated)


def _ranking(tree: Node, now: datetime):
    """Best name match first, then most recent move for dated `reached:` filters,
    otherwise longest time in stage."""
    dated = [node for node, negated in _walk(tree) if isinstance(node, Reached) and node.op and not negated]

    def key(match: Match):
        candidate = match.candidate
        if dated:
            times = [candidate.reached_at(node.stage) for node in dated]
            latest = max((at for at in times if at is not None), default=candidate.stage_entered_at)
            secondary = -latest.timestamp()
        else:
            secondary = -candidate.seconds_in_stage(now)
        return (-(match.score or 0.0), secondary, candidate.name.lower())

    return key


def _explain_empty(tree: Node, candidates: list[Candidate], now: datetime) -> str:
    """Which filter ruled everyone out, in plain English."""
    if not candidates:
        return "There are no candidates in the pipeline yet."
    clauses = list(tree.children) if isinstance(tree, And) else [tree]

    remaining = candidates
    for index, clause in enumerate(clauses):
        alone = [c for c in candidates if _evaluate(clause, c, now)[0]]
        if not alone:
            return _explain_clause(clause, clauses, now)
        narrowed = [c for c in remaining if _evaluate(clause, c, now)[0]]
        if not narrowed:
            count = len(remaining)
            so_far = phrase(And("", 0, tuple(clauses[:index])) if index > 1 else clauses[0], now)
            if count == 1:
                return f"Only 1 candidate {singular(so_far)}, {_ruled_out(clause, now, one=True)}."
            return f"{count} candidates {so_far}, {_ruled_out(clause, now, one=False)}."
        remaining = narrowed
    return "No candidates match all of these filters."


def _ruled_out(clause: Node, now: datetime, one: bool) -> str:
    """How `clause` ruled out the candidates left: "but none of them ..."."""
    if isinstance(clause, Not) and isinstance(clause.child, StageIs):
        return f"{'and they' if one else 'but they'}'re{'' if one else ' all'} in " \
               f"{stages.LABELS[clause.child.stage]}, which you excluded"
    if isinstance(clause, Not) and isinstance(clause.child, Reached) and clause.child.op is None:
        return f"{'and they' if one else 'but they'}'ve{'' if one else ' all'} reached " \
               f"{stages.LABELS[clause.child.stage]} at some point"
    if one:
        return f"and it's not someone who {singular(phrase(clause, now))}"
    return f"but none of them {phrase(clause, now)}"


def _explain_clause(clause: Node, clauses: list[Node], now: datetime) -> str:
    if isinstance(clause, Name):
        message = f"No candidate has a name like '{clause.term}'."
        # A stage typed in the name box ("who is in interview") probably meant the filter.
        words = [c.term for c in clauses if isinstance(c, Name)]
        hints = [suggest(word, stages.ALL_STAGES) for word in words if len(word) > 3]
        keyword = next((hint for hint in hints if hint), None)
        if keyword:
            message += (" The search box only looks for names."
                        f" To see who is in {stages.LABELS[keyword]}, open Filters and choose it under Current stage.")
        elif len(words) > 2:
            message += " The search box only looks for names. Use Filters for stages, dates and jobs."
        return message
    if isinstance(clause, StageIs):
        return f"Nobody is in {stages.LABELS[clause.stage]} right now."
    if isinstance(clause, Or) and all(isinstance(child, StageIs) for child in clause.children):
        return f"Nobody is in {' or '.join(stages.LABELS[child.stage] for child in clause.children)} right now."
    if isinstance(clause, Not) and isinstance(clause.child, StageIs):
        return f"Every candidate is in {stages.LABELS[clause.child.stage]}, which you excluded."
    if isinstance(clause, Not) and isinstance(clause.child, Reached) and clause.child.op is None:
        return f"Every candidate has reached {stages.LABELS[clause.child.stage]} at some point."
    if isinstance(clause, Reached) and clause.op is None:
        return f"Nobody has reached {stages.LABELS[clause.stage]} yet."
    if isinstance(clause, JobIs):
        return f"Nobody has applied for {clause.job_id}."
    if isinstance(clause, (Or, Not)):
        return f"No candidates {phrase(clause, now)}."
    return f"Nobody {singular(phrase(clause, now))}."
