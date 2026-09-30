"""Match rating: DeepSeek extracts facts, code verifies them, Jev scores three
categories, code scores budget fit and the overall. Never moves a candidate."""

import logging
import threading
from datetime import datetime

from .. import pipeline
from ..config import IST
from ..jobs import Job
from ..resumes import ResumeStorage
from ..store import Candidate, Store, utcnow
from . import AI, deepseek, evidence, jev, messages, questions
from .weights import WEIGHTS

log = logging.getLogger(__name__)

RATED = "rated"
FAILED = "failed"


class RatingTracker:
    """Ratings in progress, so a double click doesn't start two."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: set[int] = set()

    def start(self, candidate_id: int) -> bool:
        with self._lock:
            if candidate_id in self._pending:
                return False
            self._pending.add(candidate_id)
            return True

    def finish(self, candidate_id: int) -> None:
        with self._lock:
            self._pending.discard(candidate_id)

    def is_pending(self, candidate_id: int) -> bool:
        with self._lock:
            return candidate_id in self._pending


# ---- no AI ------------------------------------

def budget_fit(expected_salary: int | None, job: Job) -> dict:
    """Expected CTC vs budget, scored 1 to 5."""
    if expected_salary is None:
        return {"score": None, "rated_by": "code", "detail": "No expected CTC given"}
    midpoint = (job.budget_min + job.budget_max) / 2
    if expected_salary <= midpoint:
        score, detail = 5, "At or below the budget midpoint"
    elif expected_salary <= job.budget_max:
        score, detail = 4, "Above the midpoint, within the budget"
    elif expected_salary <= job.budget_max * 1.10:
        score, detail = 3, "Up to 10% above the budget maximum"
    elif expected_salary <= job.budget_max * 1.25:
        score, detail = 2, "10% to 25% above the budget maximum"
    else:
        score, detail = 1, "More than 25% above the budget maximum"
    return {"score": score, "rated_by": "code", "detail": detail}


def overall(scores: dict[str, float | None]) -> tuple[float | None, list[str]]:
    """2 x weighted average of the rated categories. Returns (overall, missing)."""
    rated = {category: score for category, score in scores.items() if score is not None}
    missing = [category for category in WEIGHTS if category not in rated]
    weight = sum(WEIGHTS[category] for category in rated)
    if not weight:
        return None, missing
    return round(2 * sum(WEIGHTS[c] * score for c, score in rated.items()) / weight, 1), missing


# ---- what Jev is shown -------------------------------------------------------

def jev_state(job: Job, verified: evidence.Verified, today: datetime) -> tuple[dict, dict]:
    """What Jev sees: requirements and verified facts. No name, email, salary or quotes."""
    job_state = {
        "title": job.title,
        "min_experience_years": job.min_experience_years,
        "required_skills": list(job.required_skills),
        "nice_to_have_skills": list(job.nice_to_have_skills),
    }
    candidate_state = {
        "skills": [skill["name"] for skill in verified.skills],
        "roles": [{key: role[key] for key in ("title", "organization", "start", "end")} for role in verified.roles],
        "experience": {
            "years_stated_in_resume": verified.experience["years"] if verified.experience else None,
            "years_from_role_dates": evidence.years_from_roles(verified.roles, today.date()),
        },
    }
    return job_state, candidate_state


# ---- the flow -----------------------------------------------------------------

def rate(ai: AI, job: Job, resume_text: str, expected_salary: int | None, now: datetime) -> dict:
    """Raises DeepSeekError or JevError if a model can't be used."""
    facts = deepseek.extract_facts(ai.deepseek, resume_text)
    verified = evidence.verify(facts, resume_text)
    job_state, candidate_state = jev_state(job, verified, now)
    scores, jev_model = jev.score_categories(ai.jev, job_state, candidate_state)

    categories = {
        name: {
            "score": round(result.score, 1),
            "confidence": round(result.confidence, 3),
            "rated_by": "jev",
            "needs_review": result.confidence < questions.NEEDS_REVIEW_CONFIDENCE,
        }
        for name, result in scores.items()
    }
    categories["budget"] = budget_fit(expected_salary, job)
    total, missing = overall({name: category["score"] for name, category in categories.items()})

    return {
        "status": RATED,
        "overall": total,
        "needs_review": any(category.get("needs_review") for category in categories.values()),
        "categories": categories,
        "missing": missing,
        "weights": WEIGHTS,
        "facts": {**verified.to_dict(), "years_from_role_dates": candidate_state["experience"]["years_from_role_dates"]},
        "job": job.requirements(),
        "expected_salary": expected_salary,
        "models": {"deepseek": getattr(ai.deepseek, "model", None), "jev": jev_model},
        "needs_review_below": questions.NEEDS_REVIEW_CONFIDENCE,
    }


def can_rate(candidate: Candidate, ai: AI) -> bool:
    return bool(ai.enabled and candidate.resume and candidate.resume.get("text_chars"))


def rate_candidate(store: Store, storage: ResumeStorage, ai: AI, tracker: RatingTracker, candidate_id: int) -> None:
    """Rate and record the result. Call tracker.start(candidate_id) first."""
    try:
        candidate = store.candidate(candidate_id)
        if candidate is None or not can_rate(candidate, ai):
            return
        try:
            job = store.job(candidate.job_id)
            rating = rate(ai, job, storage.text(candidate.resume["sha256"]), candidate.expected_salary, utcnow().astimezone(IST))
        except deepseek.DeepSeekError as error:
            rating = {"status": FAILED, "message": "The AI did not return usable facts from the resume.",
                      "reason": str(error)}
        except jev.JevError as error:
            rating = {"status": FAILED, "message": "The scoring service did not answer.", "reason": str(error)}
        rating["resume_sha256"] = candidate.resume["sha256"]
        pipeline.record_rating(store, candidate_id, rating)
    except Exception:  # background task: log rather than raise
        log.exception("Rating candidate %s failed", candidate_id)
    finally:
        tracker.finish(candidate_id)


def view(candidate: Candidate, ai: AI, pending: bool) -> dict:
    """Status, message and latest rating, for the profile."""
    latest = candidate.rating
    result = {
        "status": "not_rated",
        "message": messages.RATING_NOT_RATED,
        "can_rerun": can_rate(candidate, ai) and not pending,
        "rated_at": latest.at if latest else None,
        "rating": latest.data if latest and latest.data.get("status") == RATED else None,
    }
    if pending:
        result.update(status="pending", message=messages.RATING_PENDING)
    elif latest and latest.data.get("status") == RATED:
        result.update(status=RATED, message="")
    elif latest:
        result.update(status=FAILED, message=f"{messages.RATING_FAILED}: {latest.data.get('message', '')}".rstrip(": "))
    elif not candidate.resume:
        result.update(status="no_resume", message=messages.RATING_NO_RESUME)
    elif not candidate.resume.get("text_chars"):
        result.update(status="unreadable", message=messages.RATING_UNREADABLE)
    elif not ai.enabled:
        result.update(status="ai_off", message=messages.RATING_AI_OFF)
    return result
