# Recruitly

A lightweight applicant tracking system for running a hiring pipeline.

**Repository:** https://github.com/Shailly0502/Recruitly · **Summary (PDF):** [docs/Recruitly-summary.pdf](docs/Recruitly-summary.pdf) · **Full design:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

Candidates move through **Applied → Screening → Interview → Offer → Hired** and can be rejected at any point before they're hired. Recruitly keeps a tamper-evident history of every move, and has a typo-tolerant name search with ordinary filters for stage, time in stage, date reached and job.

## Features

- **Pipeline board**: everyone grouped by current stage, with how long they've been there
- **Strict stage rules**: one step forward at a time, and Hired/Rejected are final, enforced by the server
- **Audit trail**: every action is an append-only event, hash-chained so edits to the database file are detected
- **Search**: fuzzy name matching, plus filters for stage, excluded stages, time in stage, date reached and job
- **Helpful empty results**: when nothing matches, you're told which filter ruled everyone out
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

You need both keys. Without them the features are simply hidden. Set `RECRUITLY_AI=off` to disable them while keeping the keys. The APIs are only called when you press Enter on search text that matches no candidate's name, or click **Create candidate rating** on a profile.

## Usage

### Search

The search box finds candidates by name, and typos are fine. Everything else is a filter: click **Filters**, choose, and press **Apply**. Applied filters show as chips under the search box; click × on a chip to remove it.

| What you want | How |
| --- | --- |
| Find Priya Sharma (misspelled) | Type `sharam` in the search box |
| Who's in Interview right now | Current stage: Interview |
| Stuck in Screening for over a week | Current stage: Screening, Time in current stage: More than a week |
| Moved to Interview since Monday | Reached stage: Interview, When: Since Monday |
| Reached Screening before Monday, or on one day | Reached stage: Screening, When: Before Monday (or On Yesterday) |
| Never made it to Interview | Never reached: Interview |
| Reached Offer but not hired | Reached stage: Offer, Exclude stage: Hired |
| Everyone except rejected | Exclude stage: Rejected |
| Applicants for a job | Job: JOB-001 |
| Combined | Type `priya`, and choose Current stage: Interview and Offer |

Filters combine with each other and with the name. Above the results, a line always says exactly what's being searched ("Showing candidates who are currently in Screening and have been…"). Name matches rank first, then the most recent move for a "since" filter, otherwise the longest time in stage.

When nothing matches, you're told why, for example *"Only 1 candidate is currently in Offer, and it's not someone who has been in their current stage for less than 1 day."* or *"Nobody has applied for JOB-002."* Filters that can't work together are caught before searching (*"You chose Hired as the current stage but also excluded it, so nobody can match."*). A question typed into the name box gets pointed at the right filter.

### Jobs

The **Job portal** page lists every job as a plain table. Fill in the empty bottom row to add one. When adding a candidate you type the job ID, and the form shows that job's requirements.

### Plain-English search

Typing a question and pressing Enter sends it through a small pipeline. Jev decides whether it's a question at all. DeepSeek translates it, the app checks the translation and turns it into the portal's filters, describes those filters back in plain English, and Jev checks that the description matches the question. Confident translations fill in the filters and run, showing "Interpreted as: ...". Less confident ones are offered as filters you can apply or adjust first.

Any valid question runs. The parts that fit a menu fill in the Filters panel. Anything no menu can hold, like "in Offer **or** waiting over two weeks", is kept as an extra condition and shown as its own chip in plain English ("Also: are currently in Offer or have been in their current stage for more than 14 days"), which you can remove like any other filter.

Name searches never go through this and run as you type.

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
  search/          filters, evaluation and explanations, fuzzy matching (plus the internal query parser)
  resumes/         PDF storage, text extraction, page rendering
  ai/              plain-English search and candidate rating
static/            frontend (index.html, jobs.html, app.js, styles.css)
evals/             accuracy checks against the live APIs
docs/              architecture notes, summary PDF
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
| GET | `/api/search?name=&stages=&exclude=&min_days=&max_days=&reached=&reached_when=&reached_date=&not_reached=&job=` | Search with filters |
| POST | `/api/assist` | Search box text on Enter: a name, or a plain-English question turned into filters |
| GET | `/api/audit/verify` | Check the history hasn't been tampered with |
| POST | `/api/demo/seed` | Load demo data |

Errors always come back as `{error, message, position}` with a 400, 404 or 409. There are no endpoints for editing or deleting history.

## Design decisions

**History is the source of truth.** There's no `current_stage` column that could drift out of sync. A candidate's stage, time in stage and latest rating are all computed from their events.

**Append-only is enforced by the database.** SQLite triggers block `UPDATE` and `DELETE` on the events table, so even code that bypasses the API can't rewrite history. Each event also stores a hash of the previous one, so hand-editing the database file shows up in `/api/audit/verify`.

**Moves carry the stage you saw.** Every advance or reject sends the stage the screen was showing. If the candidate has already moved (say, from a double click), the request is refused rather than skipping a stage.

**Filters, not a query language.** Recruiters pick from menus instead of learning syntax. Underneath, the filters become a small query tree that does the matching, ranking and explaining. Plain-English search produces the same filters, so she can always see and adjust what ran.

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

## Where I disagreed with the AI

**How it evaluates a candidate.**

The AI's plan for rating candidates was to pull skills, roles and years of experience out of the resume, score them against the job description with a rubric, and turn that into a score out of 10. It also ran that rating automatically for every candidate as soon as they were added.

I don't think that's a sound basis for recognising a good candidate. Matching skills and counting years is a proxy for quality, not a measure of it. A strong candidate often shows up in things a rubric can't see from a job description: how fast they've grown, the impact and difficulty of their work, skills that transfer from a different stack, and whether they'd do well in this particular team. A score built only on overlap with the job description can rank a keyword-heavy resume above a better person. Then a recruiter has to double-check every number, which adds manual work instead of removing it. Learning what a good candidate looks like takes time and training on real outcomes: who was hired, who did well, and what recruiters corrected.

What I changed because of it:

- **Ratings run only when the recruiter asks.** They no longer start automatically when a candidate is added. There's a **Create candidate rating** button, so the recruiter decides when a model is involved.
- **The rating is advice, not a decision.** It never moves, rejects or hires anyone. Every fact comes with a quote from the resume, and scores the model isn't confident about are flagged "needs review".
- **A proper scoring model is first on the list below**, trained on real hiring outcomes instead of a hand-written rubric.

## What I'd do with more time

**A proper ATS scoring model**
- Train and calibrate scoring on real outcomes (who was shortlisted, hired and did well), instead of hand-set rubric weights.
- Learn from recruiters: a thumbs up or down on each rating, and corrections to extracted facts, fed back into the model.
- Look at trajectory, impact and transferable skills, not just keyword and years overlap.
- Run regular bias audits: the same resume under different names, genders and colleges must score the same, which the fairness eval already starts to check.
- Tune the thresholds and rubric wording against the evals.

**A better database**
- A normalised schema with proper foreign keys: `candidates`, `jobs`, `applications` (one candidate, many jobs), `stages` and `events`, each referencing the others.
- PostgreSQL with migrations and indexes, with filtering done in SQL instead of in memory.
- User accounts and roles, with every event recording who made the change.
- Editing jobs, with each change recorded in history.

**UI and UX for more features**
- Drag-and-drop between board columns, bulk actions (move or reject several candidates), and keyboard shortcuts.
- Saved searches ("stuck in Screening over a week" as a one-click view), notes and tags on candidates.
- Interview scheduling with calendar invites, and email templates for each stage.
- Replacing a resume, OCR for scanned resumes, and a mobile layout.

**A recruiter playground**
- A sandbox with synthetic candidates where a recruiter can try filters and plain-English questions, rate candidates, adjust the rubric and weights, and see how rankings change, all without touching real data.
- A guided tour for new recruiters built on the same sandbox.

**Other ideas**
- A pipeline analytics dashboard: time to hire, conversion at each stage, and the stages where candidates get stuck.
- Alerts, such as "5 candidates have been in Screening for over a week" or an offer that's about to expire.
- Semantic search over resumes ("has worked on payments at scale"), with the evidence highlighted.
- AI-drafted interview questions aimed at gaps in a candidate's evidence.
- Duplicate candidate detection across jobs.
- A candidate-facing status page, and integrations with job boards, email and calendars.
