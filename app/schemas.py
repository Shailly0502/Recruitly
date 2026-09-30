"""Request and response models for the API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from . import stages
from .jobs import Job
from .store import ADDED, RATED, REJECTED, Candidate, Event

Stage = Literal["applied", "screening", "interview", "offer", "hired", "rejected"]


class AdvanceIn(BaseModel):
    expected_stage: Stage


class RejectIn(BaseModel):
    expected_stage: Stage
    reason: str = Field(default="", max_length=500)


class JobIn(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$", description="e.g. JOB-002")
    title: str = Field(max_length=120)
    min_experience_years: float = Field(ge=0, le=60)
    required_skills: list[str] = Field(max_length=30)
    nice_to_have_skills: list[str] = Field(default=[], max_length=30)
    budget_min: int = Field(ge=0)
    budget_max: int = Field(ge=0)
    currency: str = Field(default="INR", pattern=r"^[A-Za-z]{3}$")
    location: str = Field(default="", max_length=80)
    work_mode: str = Field(default="", max_length=40)


class AssistIn(BaseModel):
    text: str = Field(max_length=300)
    tz_offset: int | None = Field(default=None, ge=-900, le=900)


class ErrorOut(BaseModel):
    error: str
    message: str
    position: int | None = None


class StageOut(BaseModel):
    key: str
    label: str


class JobOut(BaseModel):
    id: str
    title: str
    min_experience_years: float
    required_skills: list[str]
    nice_to_have_skills: list[str]
    budget_min: int
    budget_max: int
    currency: str
    location: str
    work_mode: str


class EventOut(BaseModel):
    id: int
    type: str
    from_stage: str | None
    to_stage: str | None
    at: datetime
    reason: str | None
    summary: str


class CandidateOut(BaseModel):
    id: int
    name: str
    email: str
    job_id: str | None
    expected_salary: int | None
    stage: str
    stage_label: str
    rejected_from: str | None
    created_at: datetime
    stage_entered_at: datetime
    seconds_in_stage: int
    days_in_stage: int
    actions: list[str]


class ResumeOut(BaseModel):
    filename: str
    pages: int
    readable: bool  # False for scans with no text


class RatingOut(BaseModel):
    status: str  # rated | pending | failed | not_rated | unreadable | no_resume | ai_off
    message: str
    can_rerun: bool
    rated_at: datetime | None
    rating: dict | None  # see ai/rating.rate


class CandidateDetailOut(CandidateOut):
    job: JobOut | None
    resume: ResumeOut | None
    rating: RatingOut
    history: list[EventOut]


class BoardOut(BaseModel):
    stages: list[StageOut]
    candidates: list[CandidateOut]


class SearchHitOut(CandidateOut):
    score: float | None


class SearchOut(BaseModel):
    query: str
    count: int
    results: list[SearchHitOut]
    explanation: str | None


class AssistOut(BaseModel):
    path: str                   # see ai/assist.py
    message: str | None
    query: str | None           # query run or suggested
    description: str | None     # that query in plain English
    confidence: float | None
    error: ErrorOut | None      # parser error for the input
    count: int
    results: list[SearchHitOut] | None  # None when nothing was run
    explanation: str | None


class AIStatusOut(BaseModel):
    deepseek: bool
    jev: bool
    search: bool
    rating: bool


class AuditOut(BaseModel):
    ok: bool
    events: int
    broken_at: int | None
    message: str


class SeedOut(BaseModel):
    added: int


def _summary(event: Event) -> str:
    if event.type == ADDED:
        job = f" for {event.data['job_id']}" if event.data.get("job_id") else ""
        return f"Applied{job}; added to the pipeline in Applied"
    if event.type == REJECTED:
        return f"Rejected while in {stages.LABELS[event.from_stage]}"
    if event.type == RATED:
        if event.data.get("status") != "rated":
            return "Match rating failed"
        review = " (needs review)" if event.data.get("needs_review") else ""
        return f"Match rating recorded: {event.data.get('overall')} / 10{review}"
    return f"Moved from {stages.LABELS[event.from_stage]} to {stages.LABELS[event.to_stage]}"


def candidate_fields(candidate: Candidate, now: datetime) -> dict:
    seconds = int(candidate.seconds_in_stage(now))
    return {
        "id": candidate.id,
        "name": candidate.name,
        "email": candidate.email,
        "job_id": candidate.job_id,
        "expected_salary": candidate.expected_salary,
        "stage": candidate.stage,
        "stage_label": stages.LABELS[candidate.stage],
        "rejected_from": candidate.rejected_from,
        "created_at": candidate.created_at,
        "stage_entered_at": candidate.stage_entered_at,
        "seconds_in_stage": seconds,
        "days_in_stage": seconds // 86400,
        "actions": stages.allowed_actions(candidate.stage),
    }


def candidate_detail(candidate: Candidate, now: datetime, job: Job | None, rating: dict) -> CandidateDetailOut:
    history = [
        EventOut(id=e.id, type=e.type, from_stage=e.from_stage, to_stage=e.to_stage, at=e.at,
                 reason=e.data.get("reason") if e.type == REJECTED else None, summary=_summary(e))
        for e in candidate.history
    ]
    resume = None
    if candidate.resume:
        resume = ResumeOut(filename=candidate.resume["filename"], pages=candidate.resume["pages"],
                           readable=candidate.resume["text_chars"] > 0)
    return CandidateDetailOut(
        **candidate_fields(candidate, now),
        job=JobOut(**job.requirements()) if job else None,
        resume=resume,
        rating=RatingOut(**rating),
        history=history,
    )
