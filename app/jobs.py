"""Jobs and their requirements. SEED_JOBS are inserted when the database is created."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    id: str
    title: str
    min_experience_years: float
    required_skills: tuple[str, ...]
    nice_to_have_skills: tuple[str, ...]
    budget_min: int  # per year
    budget_max: int
    currency: str
    location: str
    work_mode: str

    def requirements(self) -> dict:
        """Job as a dict. Also stored with each rating."""
        return {
            "id": self.id,
            "title": self.title,
            "min_experience_years": self.min_experience_years,
            "required_skills": list(self.required_skills),
            "nice_to_have_skills": list(self.nice_to_have_skills),
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "currency": self.currency,
            "location": self.location,
            "work_mode": self.work_mode,
        }


SEED_JOBS = [
    Job(
        id="JOB-001",
        title="Backend Engineer",
        min_experience_years=3,
        required_skills=("Python", "FastAPI", "SQL", "REST API design"),
        nice_to_have_skills=("Docker", "AWS", "Redis"),
        budget_min=1_800_000,
        budget_max=2_600_000,
        currency="INR",
        location="Lucknow",
        work_mode="Hybrid",
    ),
]


def normalize_id(job_id: str) -> str:
    return job_id.strip().upper()
