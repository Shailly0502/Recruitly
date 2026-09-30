# Recruitly

A lightweight applicant tracking system for running a hiring pipeline.

Candidates move through **Applied → Screening → Interview → Offer → Hired** and can be rejected at any point before they're hired. Recruitly keeps a tamper-evident history of every move, and has a single search box that handles typos, time-based filters and combined queries.

## Features

- **Pipeline board**: everyone grouped by current stage, with how long they've been there
- **Strict stage rules**: one step forward at a time, and Hired/Rejected are final, enforced by the server
- **Audit trail**: every action is an append-only event, hash-chained so edits to the database file are detected
- **Search**: fuzzy name matching, filters by stage, time in stage, date reached, job, and negation
- **Helpful errors**: a bad query tells you what's wrong and points at it, instead of returning nothing
- **Jobs and resumes**: applications are tied to a job, and resumes are shown as page images only
- **Plain-English search** (optional): type a question like "who's been stuck in screening for a week?"
- **Candidate rating** (optional): scores a candidate against the job's requirements, with the evidence shown

## Tech stack

- Python 3.11+, FastAPI, Pydantic, Uvicorn
- SQLite (standard library `sqlite3`)
- Vanilla HTML, CSS and JavaScript, with no build step
- pypdfium2 and Pillow for reading resumes
- Optional: DeepSeek and TypeSafe (Jev) APIs for plain-English search and rating

## Getting started

```bash
git clone https://github.com/Shailly0502/Recruitly.git
cd Recruitly
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload
```

On macOS/Linux use `.venv/bin/python` instead of `.venv\Scripts\python`.

Then open http://localhost:8000. The pipeline starts empty, so click **Load demo candidates** to get 14 sample candidates with history and resumes. Interactive API docs are at http://localhost:8000/docs.

Data lives in `data/` (a SQLite file plus the uploaded resumes). Delete that folder to start fresh, or point `RECRUITLY_DB` somewhere else.

### Optional: plain-English search and rating

These two features call external APIs. To turn them on, create a `.env` file in the project root:

```
DEEPSEEK_API_KEY=your-key
TYPESAFE_API_KEY=your-key
```

You need both keys. Without them the features are simply hidden. Set `RECRUITLY_AI=off` to disable them while keeping the keys. The APIs are only called when you press Enter on a search the parser can't read, or click **Create candidate rating** on a profile.

## Usage

### Search syntax

Plain words search names, and typos are fine. Everything else is a filter.

| What you want | Query |
| --- | --- |
| Find Priya Sharma (misspelled) | `sharam` |
| Who's in Interview right now | `stage:interview` |
| Stuck in Screening for over a week | `stage:screening for:>7d` |
| Moved to Interview since Monday | `reached:interview>=monday` |
| Reached Offer but not hired | `reached:offer -stage:hired` |
| Everyone except rejected | `-stage:rejected` |
| Applicants for a job | `job:JOB-001` |
| Combined | `(stage:interview OR stage:offer) priya` |

- Terms are combined with a space (AND), `OR`, `-` or `NOT`, and parentheses.
- Dates: `today`, `yesterday`, a weekday, `28-09-2026` (or `28/09/2026`, `2026-09-28`), or a relative time like `3d`.
- Durations: `12h`, `7d`, `2w`.

If you'd rather not type filters, **Apply Filters** has dropdowns that build the query for you.

When something doesn't parse, you get a pointer to the problem:

```
stage:screening for:>banana
                     ^
'banana' isn't a duration. Use a number and a unit, like 12h, 7d or 2w.
```

If a valid query matches nobody, it tells you which part ruled everyone out.

### Jobs

The **Job portal** page lists every job as a plain table. Fill in the empty bottom row to add one. When adding a candidate you type the job ID, and the form shows that job's requirements.

### Plain-English search

Typing a question and pressing Enter sends it through a small pipeline. Jev decides whether it's a question at all. DeepSeek turns it into a query. The parser validates it, the app describes it back in plain English, and Jev checks that the description matches the question. Confident translations run and show "Interpreted as: ...". Less confident ones are offered as a suggestion you can run or edit.

Normal queries and name searches never go through this and run as you type.

### Candidate rating

Click **Create candidate rating** on a candidate's profile. A spinner shows while it runs, then you get:

- **Skills, Experience and Role relevance**, each out of 5, scored by Jev from facts DeepSeek extracted from the resume
- **Budget fit** out of 5, from the expected CTC against the job's budget
- **An overall score** out of 10: `2 × (0.35·skills + 0.30·experience + 0.20·relevance + 0.15·budget)`

Every extracted fact has to come with a quote that actually appears in the resume, otherwise it's thrown out. Jev only ever sees the job requirements and those verified facts, never the candidate's name or contact details. A rating never moves a candidate. It's saved to the history like any other event, and scores Jev was unsure about are flagged "needs review".

The questions, rubrics and thresholds live in `app/ai/questions.py`, and the weights in `app/ai/weights.py`.

## Project structure

```
app/
  main.py          routes
  stages.py        stage rules
  pipeline.py      add / advance / reject / record rating
  store.py         SQLite event store and jobs table
  search/          lexer, parser, evaluation, fuzzy matching
  resumes/         PDF storage, text extraction, page rendering
  ai/              plain-English search and candidate rating
static/            frontend (index.html, jobs.html, app.js, styles.css)
evals/             accuracy checks against the live APIs
docs/              architecture notes
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design: diagrams, API reference, rubrics and failure handling.

## API

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/api/candidates` | All candidates with current stage |
| POST | `/api/candidates` | Add a candidate (multipart, with resume PDF) |
| GET | `/api/candidates/{id}` | Candidate details and history |
| POST | `/api/candidates/{id}/advance` | Move to the next stage |
| POST | `/api/candidates/{id}/reject` | Reject |
| GET | `/api/candidates/{id}/resume/pages/{n}` | A resume page as an image |
| GET / POST | `/api/candidates/{id}/rating` | Get or create a rating |
| GET / POST | `/api/jobs` | List or add jobs |
| GET | `/api/search?q=...` | Search |
| POST | `/api/assist` | Search that also accepts a plain-English question |
| GET | `/api/audit/verify` | Check the history hasn't been tampered with |
| POST | `/api/demo/seed` | Load demo data |

Errors always come back as `{error, message, position}` with a 400, 404 or 409. There are no endpoints for editing or deleting history.

## Design decisions

**History is the source of truth.** There's no `current_stage` column that could drift out of sync. A candidate's stage, time in stage and latest rating are all computed from their events.

**Append-only is enforced by the database.** SQLite triggers block `UPDATE` and `DELETE` on the events table, so even code that bypasses the API can't rewrite history. Each event also stores a hash of the previous one, so hand-editing the database file shows up in `/api/audit/verify`.

**Moves carry the stage you saw.** Every advance or reject sends the stage the screen was showing. If the candidate has already moved (say, from a double click), the request is refused rather than skipping a stage.

**A query language instead of free text.** A small grammar is predictable, fast and can explain its own errors. Plain-English search is layered on top and always shows you the query it ran.

**Separate models for writing and judging.** DeepSeek writes queries and extracts facts. Jev checks translations and scores categories. Neither one's output reaches the screen without being checked by something else.

**The overall score is a formula.** Jev scores narrow categories and the code combines them with visible weights, so it's always clear how the number was made.

**Swapped letters count as one typo.** "sharam" vs "sharma" is one transposition. Plain Levenshtein counts that as two edits, while optimal string alignment counts it as one. Words of three letters or fewer have to match exactly.

**Built for India.** All times are IST, so "since Monday" means Monday 00:00 IST. Dates are shown and accepted day-first, and money is in rupees with lakh grouping (₹24,00,000) and LPA.

**Keep it simple.** Search runs in memory, which is plenty for one company's candidates, and the frontend is plain static files.

## Known limitations

- Automated candidate scoring is regulated in some places (for example NYC's bias-audit rules and the EU AI Act). A production deployment would need a bias audit.
- A rating sends the full resume text to DeepSeek.
- Scanned resumes can be viewed but not rated, since there's no OCR.
- Resumes are shown as images to discourage downloading, but a screenshot is always possible.
- The hash chain can't detect the newest events being deleted from the end.
- No user accounts, so events don't record who made a change.
- Jobs can be added but not edited.
- A resume can't be replaced after a candidate is created.
- The rating thresholds are starting values and haven't been tuned against the evals yet.

## Roadmap

- Run the evals and tune thresholds and rubric wording
- User accounts and per-user audit entries
- Editing jobs, with changes recorded
- OCR for scanned resumes
- Notes on candidates
- Move filtering into SQL once the candidate count gets large
