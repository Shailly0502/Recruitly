"""SQLite event store.

Events are insert-only: triggers block UPDATE and DELETE, and each row stores
the previous row's hash, so edits to the file show up in verify(). All
candidate state is derived from events. The jobs table holds job descriptions.
"""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import jobs
from .jobs import Job

GENESIS_HASH = "0" * 64

ADDED = "added"
ADVANCED = "advanced"
REJECTED = "rejected"
RATED = "rated"  # match rating; doesn't change the stage

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    type         TEXT NOT NULL CHECK (type IN ('added', 'advanced', 'rejected', 'rated')),
    from_stage   TEXT,
    to_stage     TEXT,
    data         TEXT NOT NULL,
    at           TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    hash         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS events_by_candidate ON events (candidate_id, id);

CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only: history cannot be altered');
END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only: history cannot be deleted');
END;

CREATE TABLE IF NOT EXISTS jobs (
    id                   TEXT PRIMARY KEY,
    title                TEXT NOT NULL,
    min_experience_years REAL NOT NULL,
    required_skills      TEXT NOT NULL,
    nice_to_have_skills  TEXT NOT NULL,
    budget_min           INTEGER NOT NULL,
    budget_max           INTEGER NOT NULL,
    currency             TEXT NOT NULL,
    location             TEXT NOT NULL,
    work_mode            TEXT NOT NULL
);
"""


class OutdatedDatabase(Exception):
    pass


class DuplicateJob(Exception):
    pass


@dataclass(frozen=True)
class Event:
    id: int
    candidate_id: int
    type: str
    from_stage: str | None
    to_stage: str | None  # None for events that don't move the candidate
    data: dict
    at: datetime
    prev_hash: str
    hash: str


@dataclass
class Candidate:
    id: int
    name: str
    email: str
    stage: str
    created_at: datetime
    stage_entered_at: datetime
    job_id: str | None = None
    expected_salary: int | None = None
    resume: dict | None = None     # sha256, filename, pages, text_chars
    rejected_from: str | None = None
    rating: Event | None = None    # latest rating attempt
    history: list[Event] = field(default_factory=list)

    def reached_at(self, stage: str) -> datetime | None:
        """When the candidate first entered `stage`, or None if they never did."""
        for event in self.history:
            if event.to_stage == stage:
                return event.at
        return None

    def seconds_in_stage(self, now: datetime) -> float:
        return max(0.0, (now - self.stage_entered_at).total_seconds())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash(prev_hash: str, candidate_id: int, type_: str, from_stage: str | None,
          to_stage: str | None, data_text: str, at_text: str) -> str:
    payload = json.dumps([prev_hash, candidate_id, type_, from_stage, to_stage, data_text, at_text])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        candidate_id=row["candidate_id"],
        type=row["type"],
        from_stage=row["from_stage"],
        to_stage=row["to_stage"],
        data=json.loads(row["data"]),
        at=datetime.fromisoformat(row["at"]),
        prev_hash=row["prev_hash"],
        hash=row["hash"],
    )


def _to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        title=row["title"],
        min_experience_years=row["min_experience_years"],
        required_skills=tuple(json.loads(row["required_skills"])),
        nice_to_have_skills=tuple(json.loads(row["nice_to_have_skills"])),
        budget_min=row["budget_min"],
        budget_max=row["budget_max"],
        currency=row["currency"],
        location=row["location"],
        work_mode=row["work_mode"],
    )


def build_candidates(events: list[Event]) -> dict[int, Candidate]:
    """Fold events (oldest first) into the current state of every candidate."""
    candidates: dict[int, Candidate] = {}
    for event in events:
        if event.type == ADDED:
            candidates[event.candidate_id] = Candidate(
                id=event.candidate_id,
                name=event.data["name"],
                email=event.data["email"],
                stage=event.to_stage,
                created_at=event.at,
                stage_entered_at=event.at,
                job_id=event.data.get("job_id"),
                expected_salary=event.data.get("expected_salary"),
                resume=event.data.get("resume"),
            )
        candidate = candidates[event.candidate_id]
        candidate.history.append(event)
        if event.type in (ADVANCED, REJECTED):
            candidate.stage = event.to_stage
            candidate.stage_entered_at = event.at
        if event.type == REJECTED:
            candidate.rejected_from = event.from_stage
        if event.type == RATED:
            candidate.rating = event
    return candidates


class Transaction:
    """Atomic reads and appends. No update or delete."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def events(self, candidate_id: int | None = None) -> list[Event]:
        if candidate_id is None:
            rows = self._conn.execute("SELECT * FROM events ORDER BY id")
        else:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE candidate_id = ? ORDER BY id", (candidate_id,)
            )
        return [_to_event(row) for row in rows]

    def candidates(self) -> dict[int, Candidate]:
        return build_candidates(self.events())

    def candidate(self, candidate_id: int) -> Candidate | None:
        return build_candidates(self.events(candidate_id)).get(candidate_id)

    def next_candidate_id(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(candidate_id), 0) + 1 FROM events").fetchone()
        return row[0]

    def job(self, job_id: str) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (jobs.normalize_id(job_id),)).fetchone()
        return _to_job(row) if row else None

    def append(self, candidate_id: int, type_: str, from_stage: str | None, to_stage: str | None,
               data: dict, at: datetime) -> None:
        last = self._conn.execute("SELECT hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = last["hash"] if last else GENESIS_HASH
        data_text = json.dumps(data, sort_keys=True)
        at_text = at.astimezone(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO events (candidate_id, type, from_stage, to_stage, data, at, prev_hash, hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (candidate_id, type_, from_stage, to_stage, data_text, at_text, prev_hash,
             _hash(prev_hash, candidate_id, type_, from_stage, to_stage, data_text, at_text)),
        )


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.executescript(SCHEMA)
            created = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'events'").fetchone()["sql"]
            if "'rated'" not in created:
                raise OutdatedDatabase(
                    f"{self.path} was created by an older version and can't record ratings. "
                    "Delete the file and start again.")
            for job in jobs.SEED_JOBS:
                conn.execute(
                    "INSERT OR IGNORE INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (job.id, job.title, job.min_experience_years, json.dumps(job.required_skills),
                     json.dumps(job.nice_to_have_skills), job.budget_min, job.budget_max, job.currency,
                     job.location, job.work_mode))
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        # transactions are managed manually
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def transaction(self):
        """Write transaction. BEGIN IMMEDIATE locks up front so rule checks can't go stale."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield Transaction(conn)
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    @contextmanager
    def _read(self):
        conn = self._connect()
        try:
            yield Transaction(conn)
        finally:
            conn.close()

    def candidates(self) -> list[Candidate]:
        with self._read() as tx:
            return list(tx.candidates().values())

    def candidate(self, candidate_id: int) -> Candidate | None:
        with self._read() as tx:
            return tx.candidate(candidate_id)

    def jobs(self) -> list[Job]:
        conn = self._connect()
        try:
            return [_to_job(row) for row in conn.execute("SELECT * FROM jobs ORDER BY id")]
        finally:
            conn.close()

    def job(self, job_id: str) -> Job | None:
        with self._read() as tx:
            return tx.job(job_id)

    def add_job(self, job: Job) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job.id, job.title, job.min_experience_years, json.dumps(job.required_skills),
                 json.dumps(job.nice_to_have_skills), job.budget_min, job.budget_max, job.currency,
                 job.location, job.work_mode))
        except sqlite3.IntegrityError:
            raise DuplicateJob(f"A job with ID {job.id} already exists.") from None
        finally:
            conn.close()

    def verify(self) -> dict:
        """Walk the hash chain; an edited, removed or reordered row breaks it."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
        finally:
            conn.close()
        prev_hash = GENESIS_HASH
        for row in rows:
            expected = _hash(prev_hash, row["candidate_id"], row["type"], row["from_stage"],
                             row["to_stage"], row["data"], row["at"])
            if row["prev_hash"] != prev_hash or row["hash"] != expected:
                return {
                    "ok": False,
                    "events": len(rows),
                    "broken_at": row["id"],
                    "message": f"History has been altered: event {row['id']} does not match its recorded hash.",
                }
            prev_hash = row["hash"]
        return {"ok": True, "events": len(rows), "broken_at": None,
                "message": f"All {len(rows)} events are intact."}
