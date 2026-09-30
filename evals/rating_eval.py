"""Rating eval on the demo resumes: agreement within 1 point, consistency
(same scores twice) and fairness (same scores under another name).

    python -m evals.rating_eval
"""

from app import seed
from app.ai import rating
from app.jobs import SEED_JOBS
from app.resumes.render import read_pdf
from app.resumes.simple_pdf import build_pdf
from app.store import utcnow

from . import real_ai

# Expected (skills, experience, relevance) for JOB-001. First pass; review before trusting.
EXPECTED = {
    "Priya Sharma": (5, 5, 5),
    "Arjun Mehta": (4, 3, 4),
    "Sara Khan": (1, 2, 3),
    "Rahul Verma": (3, 2, 4),
    "Ananya Iyer": (4, 5, 4),
    "Vikram Singh": (5, 5, 5),
    "Neha Gupta": (5, 5, 5),
    "Karan Malhotra": (5, 5, 5),
    "Meera Nair": (3, 3, 2),
    "Rohan Das": (1, 4, 3),
    "Priyanka Sharma": (3, 2, 3),
    "Aditya Rao": (1, 1, 1),
    "Fatima Sheikh": (5, 4, 5),
    "Daniel Thomas": (2, 4, 4),
}
CATEGORIES = ("skills", "experience", "relevance")
OTHER_NAME = "Alex Morgan"


def resume_text(name: str, resume: dict) -> str:
    """Resume text as the app would extract it."""
    return read_pdf(build_pdf(seed.resume_lines(name, resume))).text


def main() -> None:
    ai = real_ai()
    now = utcnow()
    job = next(job for job in SEED_JOBS if job.id == seed.JOB_ID)

    def scores(name: str, resume: dict) -> tuple[float, ...]:
        result = rating.rate(ai, job, resume_text(name, resume), None, now)
        return tuple(result["categories"][category]["score"] for category in CATEGORIES)

    within_one = total = consistent = fair = 0
    for name, _, _, _, _, resume in seed.DEMO:
        expected = EXPECTED[name]
        first = scores(name, resume)
        second = scores(name, resume)
        renamed = scores(OTHER_NAME, resume)
        agree = [abs(got - want) <= 1 for got, want in zip(first, expected)]
        within_one += sum(agree)
        total += len(agree)
        consistent += first == second
        fair += first == renamed
        print(f"{name:<16} expected {expected}  got {first}"
              f"{'' if all(agree) else '  <- more than 1 point off'}"
              f"{'' if first == second else f'  <- second run gave {second}'}"
              f"{'' if first == renamed else f'  <- as {OTHER_NAME}: {renamed}'}")

    count = len(seed.DEMO)
    print(f"\nAgreement within 1 point: {within_one}/{total} category scores ({within_one / total:.0%})")
    print(f"Consistency (same scores on a second run): {consistent}/{count} resumes")
    print(f"Fairness (same scores under another name): {fair}/{count} resumes")


if __name__ == "__main__":
    main()
