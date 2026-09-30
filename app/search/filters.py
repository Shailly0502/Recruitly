"""Portal filters -> query tree, and back. The recruiter only ever sees filters;
the query tree underneath does the matching, ranking and explaining."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from .. import jobs, stages
from ..store import Candidate
from . import parser
from .describe import phrase
from .evaluate import Match, SearchResult, run
from .fuzzy import name_tokens
from .lexer import QueryError
from .parser import WEEKDAYS, And, InStageFor, JobIs, Name, Node, Not, Or, Reached, StageIs, when

DAY = 86400
REACHED_OPS = {"since": ">=", "before": "<", "on": "="}

# Words typed around a name ("find priya sharma"). Dropped when other words remain.
FILLER_WORDS = {"find", "show", "search", "get", "look", "lookup", "me", "for", "the", "a", "an",
                "candidate", "candidates", "named", "called", "profile", "please"}


class FilterError(Exception):
    """Filters that can't be run, with a message saying why."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Filters:
    name: str = ""                     # words matched against names, typos allowed
    stages: tuple[str, ...] = ()       # currently in any of these
    exclude: tuple[str, ...] = ()      # not currently in any of these
    min_days: float | None = None      # in the current stage for more than this
    max_days: float | None = None      # in the current stage for less than this
    reached: str | None = None         # entered this stage at some point
    reached_when: str = "since"        # since | before | on reached_date
    reached_date: str | None = None    # today, yesterday, a weekday, YYYY-MM-DD, or "3d" (3 days ago)
    not_reached: str | None = None     # never entered this stage
    job: str | None = None
    # Conditions from a plain-English question that no filter menu can hold, e.g. OR
    # across different filters. Written in the internal query syntax; shown in English.
    advanced: str = ""

    def to_dict(self) -> dict:
        return {**asdict(self), "stages": list(self.stages), "exclude": list(self.exclude)}


def search(filters: Filters, candidates: list[Candidate], now: datetime) -> SearchResult:
    """Raises FilterError if the filters can't be run. No filters: everyone, longest waiting first."""
    tree = to_tree(filters, now)
    if tree is None:
        everyone = sorted(candidates, key=lambda candidate: -candidate.seconds_in_stage(now))
        return SearchResult([Match(candidate, None) for candidate in everyone])
    return run(tree, candidates, now)


def describe_advanced(filters: Filters, now: datetime) -> str | None:
    """The `advanced` conditions in plain English, for their chip."""
    if not filters.advanced.strip():
        return None
    return phrase(_parse_advanced(filters.advanced, now), now)


def to_tree(filters: Filters, now: datetime) -> Node | None:
    clauses: list[Node] = []
    chosen = [_stage(stage) for stage in filters.stages]
    excluded = [_stage(stage) for stage in filters.exclude]
    if chosen and set(chosen) <= set(excluded):
        picked = " or ".join(stages.LABELS[stage] for stage in chosen)
        raise FilterError(f"You chose {picked} as the current stage but also excluded it, so nobody can match.")
    if len(chosen) == 1:
        clauses.append(StageIs(f"stage:{chosen[0]}", 0, chosen[0]))
    elif chosen:
        clauses.append(Or(" OR ".join(f"stage:{stage}" for stage in chosen), 0,
                          tuple(StageIs(f"stage:{stage}", 0, stage) for stage in chosen)))

    for days in (filters.min_days, filters.max_days):
        if days is not None and days <= 0:
            raise FilterError("Time in stage must be more than zero days.")
    if filters.min_days is not None and filters.max_days is not None and filters.min_days >= filters.max_days:
        raise FilterError(f"Nobody can be in a stage for more than {filters.min_days:g} days "
                          f"and less than {filters.max_days:g} days at once.")
    if filters.min_days is not None:
        clauses.append(InStageFor(f"for:>{filters.min_days:g}d", 0, ">", filters.min_days * DAY))
    if filters.max_days is not None:
        clauses.append(InStageFor(f"for:<{filters.max_days:g}d", 0, "<", filters.max_days * DAY))

    if filters.reached_date and not filters.reached:
        raise FilterError("Choose which stage they reached before choosing when.")
    if filters.reached:
        clauses.append(_reached(filters, now))
    if filters.not_reached:
        stage = _stage(filters.not_reached)
        if filters.reached == stage:
            raise FilterError(f"Nobody can have reached {stages.LABELS[stage]} and never reached it.")
        clauses.append(Not(f"-reached:{stage}", 0, Reached(f"reached:{stage}", 0, stage)))

    if filters.job:
        job_id = jobs.normalize_id(filters.job)
        clauses.append(JobIs(f"job:{job_id}", 0, job_id))

    clauses.extend(Not(f"-stage:{stage}", 0, StageIs(f"stage:{stage}", 0, stage)) for stage in excluded)

    if filters.advanced.strip():
        advanced = _parse_advanced(filters.advanced, now)
        clauses.extend(advanced.children if isinstance(advanced, And) else [advanced])

    if filters.name.strip():
        words = name_tokens(filters.name)
        if not words:
            raise FilterError(f"'{filters.name.strip()}' doesn't look like a name. Type part of a candidate's name.")
        kept = [word for word in words if word not in FILLER_WORDS]
        clauses.extend(Name(word, 0, word) for word in kept or words)

    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else And(" ".join(clause.src for clause in clauses), 0, tuple(clauses))


def from_tree(tree: Node, now: datetime) -> Filters:
    """Filters matching exactly what `tree` matches. What no menu can hold goes in `advanced`."""
    found: dict = {"stages": (), "exclude": []}
    names: list[str] = []
    leftover: list[Node] = []

    def take(key: str, value) -> bool:
        if found.get(key) is not None:
            return False
        found[key] = value
        return True

    for clause in _flatten(tree):
        if isinstance(clause, Name):
            names.append(clause.term)
        elif _stages_of(clause) is not None and not found["stages"]:
            found["stages"] = tuple(_stages_of(clause))
        elif isinstance(clause, Not) and _stages_of(clause.child) is not None:
            found["exclude"] += _stages_of(clause.child)
        elif isinstance(clause, InStageFor) and take("min_days" if clause.op in (">", ">=") else "max_days",
                                                    round(clause.seconds / DAY, 3)):
            pass
        elif isinstance(clause, Reached) and found.get("reached") is None and _reached_filter(clause, now):
            found["reached"] = clause.stage
            if clause.op is not None:
                found["reached_when"], found["reached_date"] = _reached_filter(clause, now)
        elif isinstance(clause, Not) and isinstance(clause.child, Reached) and clause.child.op is None \
                and take("not_reached", clause.child.stage):
            pass
        elif isinstance(clause, JobIs) and take("job", clause.job_id):
            pass
        else:
            leftover.append(clause)

    found["exclude"] = tuple(dict.fromkeys(found["exclude"]))
    return Filters(name=" ".join(names), advanced=" ".join(f"({clause.src})" for clause in leftover), **found)


def _parse_advanced(text: str, now: datetime) -> Node:
    try:
        return parser.parse(text, now)
    except QueryError as error:
        raise FilterError(f"The conditions from your question couldn't be read: {error.message}") from None


def _reached(filters: Filters, now: datetime) -> Reached:
    stage = _stage(filters.reached)
    if not filters.reached_date:
        return Reached(f"reached:{stage}", 0, stage)
    if filters.reached_when not in REACHED_OPS:
        raise FilterError("Choose since, before or on.")
    try:
        start, end = when(filters.reached_date.strip().lower(), now)
    except QueryError as error:
        raise FilterError(error.message) from None
    op = REACHED_OPS[filters.reached_when]
    if op == "=" and start == end:
        raise FilterError("'On' needs a whole day, like today, yesterday or Monday.")
    return Reached(f"reached:{stage}{op}{filters.reached_date}", 0, stage, op, start, end)


def _reached_filter(node: Reached, now: datetime) -> tuple[str, str] | None | bool:
    """(when, date) for a dated `reached`, True for an undated one."""
    if node.op is None:
        return True
    if node.end > node.start:  # a whole day
        day = node.start
        if node.op in (">", "<="):  # after Monday = since Tuesday; on or before Monday = before Tuesday
            day += timedelta(days=1)
        return {">=": "since", ">": "since", "<": "before", "<=": "before", "=": "on"}[node.op], _day(day, now)
    if node.op == "=":
        return None
    hours = round((now - node.start).total_seconds() / 3600)
    ago = f"{hours // 24}d" if hours % 24 == 0 else f"{hours}h"
    return ("since" if node.op in (">", ">=") else "before"), ago


def _day(day: datetime, now: datetime) -> str:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    days_back = (today.date() - day.date()).days
    if days_back == 0:
        return "today"
    if days_back == 1:
        return "yesterday"
    if 1 < days_back < 7:
        return WEEKDAYS[day.weekday()]
    return f"{day:%Y-%m-%d}"


def _stage(value: str) -> str:
    stage = value.strip().lower()
    if stage not in stages.ALL_STAGES:
        raise FilterError(f"'{value}' isn't a stage. The stages are {', '.join(stages.ALL_STAGES)}.")
    return stage


def _flatten(node: Node):
    if isinstance(node, And):
        for child in node.children:
            yield from _flatten(child)
    else:
        yield node


def _stages_of(node: Node) -> list[str] | None:
    """The stages if `node` is "in stage A" or "in A or B", else None."""
    if isinstance(node, StageIs):
        return [node.stage]
    if isinstance(node, Or) and all(isinstance(child, StageIs) for child in node.children):
        return [child.stage for child in node.children]
    return None
