"""Writes to the audit trail: add, advance, reject, and recording a rating.
Each checks the rules and appends one event in a transaction."""

from datetime import datetime

from . import stages
from .resumes import ResumeRecord
from .stages import InvalidMove
from .store import ADDED, ADVANCED, RATED, REJECTED, Candidate, Store, Transaction, utcnow


class NotFound(Exception):
    pass


class InvalidInput(ValueError):
    pass


class DuplicateCandidate(Exception):
    pass


class StaleStage(InvalidMove):
    """The candidate moved since the page was loaded."""


def add_candidate(store: Store, name: str, email: str, job_id: str, resume: ResumeRecord,
                  expected_salary: int | None = None, at: datetime | None = None) -> Candidate:
    """Record an application. The resume's hash is stored with it."""
    name = " ".join(name.split())
    email = email.strip().lower()
    if not name:
        raise InvalidInput("Name is required.")
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise InvalidInput("Enter a valid email address.")
    if expected_salary is not None and expected_salary <= 0:
        raise InvalidInput("Expected salary must be more than zero.")

    with store.transaction() as tx:
        job = tx.job(job_id)
        if job is None:
            raise InvalidInput(f"No job with ID '{job_id.strip()}'.")
        for existing in tx.candidates().values():
            if existing.email == email and existing.job_id == job.id:
                raise DuplicateCandidate(f"{existing.name} has already applied for {job.id} with {email}.")
        candidate_id = tx.next_candidate_id()
        data = {"name": name, "email": email, "job_id": job.id, "expected_salary": expected_salary,
                "resume": resume.to_dict()}
        tx.append(candidate_id, ADDED, None, stages.APPLIED, data, at or utcnow())
        return tx.candidate(candidate_id)


def record_rating(store: Store, candidate_id: int, rating: dict, at: datetime | None = None) -> Candidate:
    """Append a rating. Doesn't change the stage."""
    with store.transaction() as tx:
        candidate = _load(tx, candidate_id)
        tx.append(candidate_id, RATED, None, None, rating, _when(candidate, at))
        return tx.candidate(candidate_id)


def advance(store: Store, candidate_id: int, expected_stage: str, at: datetime | None = None) -> Candidate:
    with store.transaction() as tx:
        candidate = _load(tx, candidate_id)
        target = stages.next_stage(candidate.stage)
        _check_not_stale(candidate, expected_stage)
        tx.append(candidate_id, ADVANCED, candidate.stage, target, {}, _when(candidate, at))
        return tx.candidate(candidate_id)


def reject(store: Store, candidate_id: int, expected_stage: str, reason: str = "",
           at: datetime | None = None) -> Candidate:
    with store.transaction() as tx:
        candidate = _load(tx, candidate_id)
        stages.check_can_reject(candidate.stage)
        _check_not_stale(candidate, expected_stage)
        data = {"reason": reason.strip()} if reason.strip() else {}
        tx.append(candidate_id, REJECTED, candidate.stage, stages.REJECTED, data, _when(candidate, at))
        return tx.candidate(candidate_id)


def _load(tx: Transaction, candidate_id: int) -> Candidate:
    candidate = tx.candidate(candidate_id)
    if candidate is None:
        raise NotFound(f"No candidate with id {candidate_id}.")
    return candidate


def _check_not_stale(candidate: Candidate, expected_stage: str) -> None:
    # Stops a double click from moving a candidate two stages.
    if candidate.stage != expected_stage:
        label = stages.LABELS.get(expected_stage, expected_stage)
        raise StaleStage(f"{candidate.name} is no longer in {label}; refresh and try again.")


def _when(candidate: Candidate, at: datetime | None) -> datetime:
    at = at or utcnow()
    if at < candidate.history[-1].at:
        raise InvalidInput("An event cannot be dated before the candidate's previous event.")
    return at
