"""Search eval: 30 questions with expected queries. A translation is correct if
it returns the same candidates as the expected query.

    python -m evals.search_eval
"""

import tempfile
from pathlib import Path

from app import seed
from app.ai import assist, questions
from app.resumes import ResumeStorage
from app.search import parser, run
from app.store import Store, utcnow

from . import real_ai

# (question, expected query). Every expected query must parse.
QUESTIONS = [
    ("who is in interview right now?", "stage:interview"),
    ("show me everyone in screening", "stage:screening"),
    ("who has been stuck in screening for more than a week?", "stage:screening for:>7d"),
    ("who moved to interview since monday?", "reached:interview>=monday"),
    ("who reached the offer stage but didn't get hired?", "reached:offer -stage:hired"),
    ("everyone except rejected candidates", "-stage:rejected"),
    ("who got hired?", "stage:hired"),
    ("which candidates were rejected?", "stage:rejected"),
    ("candidates waiting in applied for more than 3 days", "stage:applied for:>3d"),
    ("who has been in offer for over two weeks", "stage:offer for:>2w"),
    ("who is in interview or offer", "stage:interview OR stage:offer"),
    ("is anyone named priya in interview or offer?", "(stage:interview OR stage:offer) priya"),
    ("who entered screening today?", "reached:screening=today"),
    ("who was rejected in the last 10 days", "reached:rejected>=10d"),
    ("who reached interview before monday", "reached:interview<monday"),
    ("people who never made it to interview", "-reached:interview"),
    ("who has made it to interview at some point", "reached:interview"),
    ("who is still in the running, neither hired nor rejected", "-stage:hired -stage:rejected"),
    ("who applied in the last week", "reached:applied>=7d"),
    ("who joined the pipeline yesterday", "reached:applied=yesterday"),
    ("who has been in their current stage for more than two weeks", "for:>14d"),
    ("who has been in interview for less than a day", "stage:interview for:<1d"),
    ("candidates called sharma who are past the applied stage", "sharma -stage:applied"),
    ("who got to offer in the last 7 days", "reached:offer>=7d"),
    ("everyone who applied for JOB-001", "job:JOB-001"),
    ("JOB-001 applicants currently in screening", "job:JOB-001 stage:screening"),
    ("who was hired since 2026-09-01", "reached:hired>=2026-09-01"),
    ("who is not in screening or interview", "-stage:screening -stage:interview"),
    ("rejected candidates who had reached interview", "stage:rejected reached:interview"),
    ("who moved to screening since friday", "reached:screening>=friday"),
]


def main() -> None:
    ai = real_ai()
    folder = Path(tempfile.mkdtemp())
    store = Store(folder / "eval.db")
    now = utcnow().astimezone()
    seed.seed(store, ResumeStorage(folder / "resumes"), now)
    candidates = store.candidates()

    def found(query: str) -> set[str]:
        return {match.candidate.name for match in run(parser.parse(query, now), candidates, now).matches}

    correct = run_automatically = suggested = 0
    for question, expected in QUESTIONS:
        outcome = assist.assist(ai, question, candidates, now)
        ok = outcome.query is not None and found(outcome.query) == found(expected)
        correct += ok
        run_automatically += outcome.path == assist.INTERPRETED
        suggested += outcome.path == assist.SUGGESTION
        confidence = "" if outcome.confidence is None else f" p={outcome.confidence:.2f}"
        print(f"{'ok  ' if ok else 'MISS'} {outcome.path:<15}{confidence:<8} {question}")
        if not ok:
            print(f"       expected {expected!r}, got {outcome.query!r}")

    total = len(QUESTIONS)
    print(f"\nCorrect: {correct}/{total} ({correct / total:.0%})")
    print(f"Run automatically: {run_automatically}, offered as a suggestion: {suggested}, "
          f"other: {total - run_automatically - suggested} (threshold {questions.TRANSLATION_OK_THRESHOLD})")


if __name__ == "__main__":
    main()
