"""API routes. Validate input, call the core modules, map errors to one JSON shape."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ai as ai_layer
from . import config, jobs, pipeline, schemas, seed, stages
from .ai import assist as assist_flow
from .ai import rating
from .jobs import Job
from .resumes import InvalidResume, ResumeStorage
from .resumes.render import MAX_BYTES
from .search import QueryError, SearchResult, search
from .store import Candidate, DuplicateJob, Store, utcnow

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
DEFAULT_DB = "data/recruitly.db"

ERRORS = {400: {"model": schemas.ErrorOut}, 404: {"model": schemas.ErrorOut}, 409: {"model": schemas.ErrorOut}}


def _error(status: int, error: str, message: str, position: int | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": error, "message": message, "position": position})


def _local(now: datetime, tz_offset: int | None) -> datetime:
    """Recruiter's local time, for "monday" and "today"."""
    return now.astimezone() if tz_offset is None else now.astimezone(timezone(timedelta(minutes=-tz_offset)))


def _skills(names: list[str]) -> tuple[str, ...]:
    return tuple(name.strip() for name in names if name.strip())


def _hits(result: SearchResult | None, now: datetime) -> list[dict] | None:
    if result is None:
        return None
    return [
        {**schemas.candidate_fields(match.candidate, now),
         "score": None if match.score is None else round(match.score, 3)}
        for match in result.matches
    ]


def create_app(db_path: str | Path | None = None, ai: ai_layer.AI | None = None) -> FastAPI:
    """`ai` overrides the AI clients; by default they're built from the environment."""
    store = Store(db_path or os.environ.get("RECRUITLY_DB", DEFAULT_DB))
    storage = ResumeStorage(store.path.parent / "resumes")  # outside static/, never served
    ai = ai or ai_layer.build(config.load_settings())
    tracker = rating.RatingTracker()
    app = FastAPI(title="Recruitly Portal", description="A hiring pipeline with an append-only history.")

    @app.exception_handler(pipeline.NotFound)
    async def not_found(request: Request, exc: pipeline.NotFound):
        return _error(404, "not_found", str(exc))

    @app.exception_handler(stages.InvalidMove)
    async def invalid_move(request: Request, exc: stages.InvalidMove):
        return _error(409, "invalid_move", str(exc))

    @app.exception_handler(pipeline.DuplicateCandidate)
    async def duplicate(request: Request, exc: pipeline.DuplicateCandidate):
        return _error(409, "duplicate_candidate", str(exc))

    @app.exception_handler(seed.NotEmpty)
    async def not_empty(request: Request, exc: seed.NotEmpty):
        return _error(409, "not_empty", str(exc))

    @app.exception_handler(DuplicateJob)
    async def duplicate_job(request: Request, exc: DuplicateJob):
        return _error(409, "duplicate_job", str(exc))

    @app.exception_handler(QueryError)
    async def invalid_query(request: Request, exc: QueryError):
        return _error(400, "invalid_query", exc.message, exc.position)

    @app.exception_handler(pipeline.InvalidInput)
    async def invalid_input(request: Request, exc: pipeline.InvalidInput):
        return _error(400, "invalid_input", str(exc))

    @app.exception_handler(InvalidResume)
    async def invalid_resume(request: Request, exc: InvalidResume):
        return _error(400, "invalid_input", str(exc))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first["loc"] if part not in ("body", "query", "path"))
        return _error(400, "invalid_input", f"{field}: {first['msg']}" if field else first["msg"])

    def load(candidate_id: int) -> Candidate:
        candidate = store.candidate(candidate_id)
        if candidate is None:
            raise pipeline.NotFound(f"No candidate with id {candidate_id}.")
        return candidate

    def detail(candidate: Candidate) -> schemas.CandidateDetailOut:
        job = store.job(candidate.job_id) if candidate.job_id else None
        return schemas.candidate_detail(
            candidate, utcnow(), job, rating.view(candidate, ai, tracker.is_pending(candidate.id)))

    def start_rating(candidate: Candidate, background: BackgroundTasks) -> bool:
        """Run a rating after the response. False if it can't run or is already running."""
        if not rating.can_rate(candidate, ai) or not tracker.start(candidate.id):
            return False
        background.add_task(rating.rate_candidate, store, storage, ai, tracker, candidate.id)
        return True

    # ---- pipeline ----

    @app.get("/api/candidates", response_model=schemas.BoardOut)
    def board():
        now = utcnow()
        return {
            "stages": [{"key": stage, "label": stages.LABELS[stage]} for stage in stages.ALL_STAGES],
            "candidates": [schemas.candidate_fields(c, now) for c in store.candidates()],
        }

    @app.post("/api/candidates", response_model=schemas.CandidateDetailOut, status_code=201, responses=ERRORS)
    def add_candidate(
        name: str = Form(max_length=120),
        email: str = Form(max_length=254),
        job_id: str = Form(max_length=40),
        expected_salary: str = Form(default="", max_length=20, description="Per year, in the job's currency. Optional."),
        resume: UploadFile | None = File(default=None, description="The resume, as a PDF. Required."),
    ):
        if resume is None:
            raise pipeline.InvalidInput("A resume PDF is required.")
        salary = None
        if expected_salary.strip():
            digits = expected_salary.replace(",", "").strip()
            if not digits.isdigit():
                raise pipeline.InvalidInput("Expected salary must be a whole number, like 2200000.")
            salary = int(digits)
        if store.job(job_id) is None:  # fail before saving the file
            raise pipeline.InvalidInput(f"No job with ID '{job_id.strip()}'.")
        record = storage.save(resume.file.read(MAX_BYTES + 1), resume.filename or "")
        return detail(pipeline.add_candidate(store, name, email, job_id, record, salary))

    @app.get("/api/candidates/{candidate_id}", response_model=schemas.CandidateDetailOut, responses=ERRORS)
    def get_candidate(candidate_id: int):
        return detail(load(candidate_id))

    @app.post("/api/candidates/{candidate_id}/advance", response_model=schemas.CandidateDetailOut, responses=ERRORS)
    def advance(candidate_id: int, body: schemas.AdvanceIn):
        return detail(pipeline.advance(store, candidate_id, body.expected_stage))

    @app.post("/api/candidates/{candidate_id}/reject", response_model=schemas.CandidateDetailOut, responses=ERRORS)
    def reject(candidate_id: int, body: schemas.RejectIn):
        return detail(pipeline.reject(store, candidate_id, body.expected_stage, body.reason))

    # ---- jobs and resumes ----

    @app.get("/api/jobs", response_model=list[schemas.JobOut])
    def list_jobs():
        return [job.requirements() for job in store.jobs()]

    @app.post("/api/jobs", response_model=schemas.JobOut, status_code=201, responses=ERRORS)
    def add_job(body: schemas.JobIn):
        """Add a job. Jobs can't be edited."""
        if body.budget_min > body.budget_max:
            raise pipeline.InvalidInput("Budget minimum can't be more than the maximum.")
        job = Job(
            id=jobs.normalize_id(body.id), title=body.title.strip(),
            min_experience_years=body.min_experience_years,
            required_skills=_skills(body.required_skills), nice_to_have_skills=_skills(body.nice_to_have_skills),
            budget_min=body.budget_min, budget_max=body.budget_max, currency=body.currency.strip().upper(),
            location=body.location.strip(), work_mode=body.work_mode.strip(),
        )
        if not job.title or not job.required_skills:
            raise pipeline.InvalidInput("A job needs a title and at least one required skill.")
        store.add_job(job)
        return job.requirements()

    @app.get("/api/jobs/{job_id}", response_model=schemas.JobOut, responses=ERRORS)
    def get_job(job_id: str):
        job = store.job(job_id)
        if job is None:
            raise pipeline.NotFound(f"No job with ID '{job_id}'.")
        return job.requirements()

    @app.get("/api/candidates/{candidate_id}/resume/pages/{number}", responses=ERRORS,
             response_class=Response)
    def resume_page(candidate_id: int, number: int):
        """One resume page as PNG. The PDF itself is never served."""
        candidate = load(candidate_id)
        image = storage.page_image(candidate.resume["sha256"], number) if candidate.resume else None
        if image is None:
            raise pipeline.NotFound(f"No page {number} in this resume.")
        return Response(image, media_type="image/png", headers={
            "Cache-Control": "no-store, max-age=0",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
        })

    # ---- rating ----

    @app.get("/api/candidates/{candidate_id}/rating", response_model=schemas.RatingOut, responses=ERRORS)
    def get_rating(candidate_id: int):
        candidate = load(candidate_id)
        return rating.view(candidate, ai, tracker.is_pending(candidate_id))

    @app.post("/api/candidates/{candidate_id}/rating", response_model=schemas.RatingOut, status_code=202,
              responses=ERRORS)
    def create_rating(candidate_id: int, background: BackgroundTasks):
        """Start a rating. Poll GET .../rating until the status isn't 'pending'."""
        candidate = load(candidate_id)
        start_rating(candidate, background)
        return rating.view(candidate, ai, tracker.is_pending(candidate_id))

    # ---- search ----

    @app.get("/api/search", response_model=schemas.SearchOut, responses=ERRORS)
    def search_candidates(
        q: str = Query(max_length=300),
        tz_offset: int | None = Query(
            default=None, ge=-900, le=900,
            description="Minutes behind UTC, as JavaScript's getTimezoneOffset() reports it. "
                        "Decides when 'monday' and 'today' begin. Defaults to the server's time zone.",
        ),
    ):
        now = utcnow()
        result = search(q, store.candidates(), _local(now, tz_offset))
        return {"query": q, "count": len(result.matches), "results": _hits(result, now),
                "explanation": result.explanation}

    @app.post("/api/assist", response_model=schemas.AssistOut, responses=ERRORS)
    def assist(body: schemas.AssistIn):
        """Search that also accepts plain English. Same as /api/search without AI."""
        now = utcnow()
        outcome = assist_flow.assist(ai, body.text, store.candidates(), _local(now, body.tz_offset))
        error = outcome.error
        return {
            "path": outcome.path,
            "message": outcome.message,
            "query": outcome.query,
            "description": outcome.description,
            "confidence": None if outcome.confidence is None else round(outcome.confidence, 3),
            "error": {"error": "invalid_query", "message": error.message, "position": error.position} if error else None,
            "count": len(outcome.result.matches) if outcome.result else 0,
            "results": _hits(outcome.result, now),
            "explanation": outcome.result.explanation if outcome.result else None,
        }

    @app.get("/api/ai/status", response_model=schemas.AIStatusOut)
    def ai_status():
        return {"deepseek": ai.deepseek is not None, "jev": ai.jev is not None,
                "search": ai.enabled, "rating": ai.enabled}

    # ---- audit and demo ----

    @app.get("/api/audit/verify", response_model=schemas.AuditOut)
    def verify_audit():
        return store.verify()

    @app.post("/api/demo/seed", response_model=schemas.SeedOut, status_code=201, responses=ERRORS)
    def seed_demo():
        return {"added": len(seed.seed(store, storage))}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/jobs", include_in_schema=False)
    def jobs_page():
        return FileResponse(STATIC_DIR / "jobs.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
