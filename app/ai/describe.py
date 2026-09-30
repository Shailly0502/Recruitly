"""Parsed query -> plain English. Deterministic, so Jev can check it."""

from datetime import datetime

from .. import stages
from ..search.parser import And, InStageFor, JobIs, Name, Node, Not, Or, Reached, StageIs

_MORE_LESS = {">": "more than", ">=": "at least", "<": "less than", "<=": "at most"}
_DAY = {">=": "on or after", ">": "after", "<": "before", "<=": "on or before", "=": "on"}


def describe(tree: Node, now: datetime) -> str:
    """`now` must match the time the query was parsed with."""
    return "Candidates who " + _clause(tree, now, top=True)


def _clause(node: Node, now: datetime, top: bool = False) -> str:
    if isinstance(node, Name):
        return f"have a name like '{node.term}'"
    if isinstance(node, StageIs):
        return f"are currently in {stages.LABELS[node.stage]}"
    if isinstance(node, InStageFor):
        return f"have been in their current stage for {_MORE_LESS[node.op]} {_duration(node.seconds)}"
    if isinstance(node, Reached):
        return _reached(node, now)
    if isinstance(node, JobIs):
        return f"applied for {node.job_id}"
    if isinstance(node, Not):
        return _negated(node.child, now)
    if isinstance(node, And):
        parts, children = [], list(node.children)
        while children:
            child = children.pop(0)
            # Merge "in Screening" + "for more than 7 days".
            if isinstance(child, StageIs) and children and isinstance(children[0], InStageFor):
                waited = children.pop(0)
                parts.append(f"have been in {stages.LABELS[child.stage]} for "
                             f"{_MORE_LESS[waited.op]} {_duration(waited.seconds)}")
            else:
                parts.append(_clause(child, now))
        joined = " and ".join(parts)
    else:
        joined = " or ".join(_clause(child, now) for child in node.children)
    return joined if top else f"({joined})"


def _negated(node: Node, now: datetime) -> str:
    if isinstance(node, StageIs):
        return f"are not currently in {stages.LABELS[node.stage]}"
    if isinstance(node, Reached) and node.op is None:
        return f"never reached {stages.LABELS[node.stage]}"
    if isinstance(node, Name):
        return f"do not have a name like '{node.term}'"
    if isinstance(node, JobIs):
        return f"did not apply for {node.job_id}"
    if isinstance(node, Not):
        return _clause(node.child, now)
    inner = _clause(node, now)
    return f"do not match: {inner}" if inner.startswith("(") else f"do not match: ({inner})"


def _reached(node: Reached, now: datetime) -> str:
    stage = stages.LABELS[node.stage]
    if node.op is None:
        return f"reached {stage} at some point"
    if node.end > node.start:  # a whole day
        return f"reached {stage} {_DAY[node.op]} {node.start:%A} {node.start.day} {node.start:%B %Y}"
    ago = _duration((now - node.start).total_seconds())
    if node.op in (">", ">="):
        return f"reached {stage} within the last {ago}"
    return f"reached {stage} more than {ago} ago"


def _duration(seconds: float) -> str:
    for size, unit in ((86400, "day"), (3600, "hour")):
        if seconds >= size and seconds % size == 0:
            count = int(seconds // size)
            return f"{count} {unit}" if count == 1 else f"{count} {unit}s"
    days = round(seconds / 86400, 1)
    return f"{days:g} days"
