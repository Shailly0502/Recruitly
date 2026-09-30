"""Stages and the moves allowed between them. Pure rules: no database, no HTTP."""

APPLIED = "applied"
SCREENING = "screening"
INTERVIEW = "interview"
OFFER = "offer"
HIRED = "hired"
REJECTED = "rejected"

# The forward path, in order. Rejected sits outside it.
PIPELINE = [APPLIED, SCREENING, INTERVIEW, OFFER, HIRED]
ALL_STAGES = PIPELINE + [REJECTED]
FINAL_STAGES = {HIRED, REJECTED}

LABELS = {stage: stage.capitalize() for stage in ALL_STAGES}


class InvalidMove(Exception):
    """A move the pipeline rules do not allow."""


def is_final(stage: str) -> bool:
    return stage in FINAL_STAGES


def next_stage(stage: str) -> str:
    """The one stage a candidate can advance to from `stage`."""
    if stage == HIRED:
        raise InvalidMove("Already hired; final outcomes can't be changed.")
    if stage == REJECTED:
        raise InvalidMove("Already rejected; final outcomes can't be changed.")
    return PIPELINE[PIPELINE.index(stage) + 1]


def check_can_reject(stage: str) -> None:
    if stage == HIRED:
        raise InvalidMove("Already hired; final outcomes can't be changed.")
    if stage == REJECTED:
        raise InvalidMove("Already rejected; final outcomes can't be changed.")


def allowed_actions(stage: str) -> list[str]:
    """Actions available from `stage`."""
    return [] if is_final(stage) else ["advance", "reject"]
