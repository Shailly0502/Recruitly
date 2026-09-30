# Recruitly architecture

Recruitly helps a recruiter run a hiring pipeline. Candidates move through **Applied → Screening → Interview → Offer → Hired**, and can be rejected at any point before being hired. The portal shows everyone grouped by stage, keeps a history that can never be altered, and offers a typo-tolerant name search with filters for stage, time in stage, when a stage was reached (or never reached) and job.

The core is built without AI. Every requirement is met with deterministic code, so it runs with no API keys and gives the same answer every time. An optional AI layer adds two features on top: asking search questions in plain English, and rating how well a candidate matches the job. With no API keys configured, the AI features are hidden and everything else works normally.

This document describes what is built. Where the build differs from the original design, the difference is listed at the end under [Changes from the original design](#changes-from-the-original-design).

## Contents

- [What the brief asks for](#what-the-brief-asks-for)
- [Tech stack](#tech-stack)
- [System architecture](#system-architecture)
- [API](#api)
- [Core components](#core-components)
- [The AI layer](#the-ai-layer)
- [Feature 1: ask in plain English](#feature-1-ask-in-plain-english)
- [Feature 2: candidate match rating](#feature-2-candidate-match-rating)
- [Guardrails](#guardrails)
- [Questions and thresholds](#questions-and-thresholds)
- [Failure handling](#failure-handling)
- [Privacy](#privacy)
- [Evaluation](#evaluation)
- [Project layout](#project-layout)
- [Configuration](#configuration)
- [Build order](#build-order)
- [Changes from the original design](#changes-from-the-original-design)

## What the brief asks for

| Area | Requirement |
| --- | --- |
| Pipeline | Add candidates; see everyone grouped by current stage |
| Pipeline | Move one stage at a time; no skipping; no reversing Hired or Rejected |
| Pipeline | Candidate view with full history and time in current stage |
| Audit | History is an audit trail: once recorded, never altered |
| Search | Typo-tolerant names ("sharam" finds Priya Sharma) |
| Search | Current stage; time in stage; entered stage since a date; reached a stage in the past; negation |
| Search | Combine filters; best matches first; explain invalid input instead of returning nothing |

## Tech stack

| Layer | Choice | Why |
| --- | --- | --- |
| Frontend | HTML, CSS, vanilla JavaScript | No framework or build step; nothing extra for reviewers to install |
| Backend | FastAPI (Python 3.11+), Uvicorn | Typed routes, automatic API docs, serves the frontend too |
| Validation | Pydantic | Ships with FastAPI; request and response models |
| Database | SQLite (built-in `sqlite3`) | Single file, zero setup; triggers enforce the audit rule |
| Resumes | pypdfium2, Pillow | Extract text and render page images from a PDF |
| AI (optional) | DeepSeek over its OpenAI-compatible HTTP API (`httpx2`); TypeSafe Python SDK (`typesafe-sdk`) for Jev | DeepSeek writes; Jev judges |

Running it:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload
# open http://localhost:8000
```

## System architecture

The core modules (`stages`, `pipeline`, `store`, `search`) are plain Python with no FastAPI imports and no knowledge of the AI layer. Routes are a thin layer that validates input and calls them. The AI layer is one more set of modules that calls into the core: a translated question becomes the same filters the recruiter could have chosen by hand, and a rating is written through the same append-only path as every other event.

```mermaid
flowchart TB
    browser["Browser (HTML / CSS / vanilla JS)<br/>name search + filters · pipeline board · candidate panel · job portal"]
    routes["Routes: app/main.py + schemas.py<br/>Pydantic validation · one error shape · 400 / 404 / 409"]
    pipeline["pipeline.py + stages.py<br/>stage rules · add / advance / reject · record a rating"]
    search["search/<br/>filters → query tree<br/>match + rank · fuzzy names · explained empty results"]
    ai["ai/ (optional)<br/>assist.py: English → filters<br/>rating.py: resume → rating"]
    store["store.py: SQLite<br/>events table: INSERT only, hash-chained<br/>jobs table"]
    resumes["resumes/<br/>PDF → text + page images, filed by hash"]
    models["DeepSeek · Jev"]

    browser -- "fetch() → JSON" --> routes
    routes -- commands --> pipeline
    routes -- queries --> search
    routes --> ai
    routes --> resumes
    pipeline -- "append only" --> store
    store -- reads --> search
    ai --> search
    ai -- "append a rating" --> pipeline
    ai --> models
```

The FastAPI server also serves the frontend from `static/`.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/candidates` | Board data: every candidate, current stage, time in stage |
| POST | `/api/candidates` | Add an application. Multipart: name, email, job ID, expected CTC (optional), resume PDF (required) |
| GET | `/api/candidates/{id}` | Stage, time in stage, job, resume details, rating, full history |
| POST | `/api/candidates/{id}/advance` | Move forward one stage `{expected_stage}` |
| POST | `/api/candidates/{id}/reject` | Reject `{expected_stage, reason}` |
| GET | `/api/candidates/{id}/resume/pages/{n}` | One rendered resume page image: the only way to view a resume |
| GET | `/api/candidates/{id}/rating` | Latest rating: categories, evidence, overall, confidence, status |
| POST | `/api/candidates/{id}/rating` | Create or re-run the rating (adds a new event). Returns 202; poll the GET until the status is no longer `pending` |
| GET | `/api/jobs` | Jobs and their requirements |
| GET | `/api/jobs/{id}` | One job, looked up by ID in any case |
| POST | `/api/jobs` | Add a job. Jobs can't be edited afterwards |
| GET | `/api/search?name=…&stages=…&exclude=…&min_days=…&max_days=…&reached=…&reached_when=…&reached_date=…&not_reached=…&job=…&advanced=…` | Ranked results with a plain-English description of the filters, or an explanation of why nobody matched. Never uses AI |
| POST | `/api/assist` | Search box text on Enter, with the filters already applied: path taken, the filters to show, description, results |
| GET | `/api/ai/status` | Which AI features are available (both keys configured?) |
| GET | `/api/audit/verify` | Checks the history hash chain is intact |
| POST | `/api/demo/seed` | Loads 14 demo candidates with backdated history and made-up resumes (empty pipeline only) |

There are deliberately **no** endpoints to edit or delete history. Errors share one shape so the frontend can display them directly:

```json
{ "error": "invalid_filter",
  "message": "You chose Hired as the current stage but also excluded it, so nobody can match.",
  "position": null }
```

Status codes: `400` bad filters or input · `404` unknown candidate or job · `409` a move the rules do not allow (for example "Already hired; final outcomes can't be changed." or "Priya Sharma is no longer in Screening; refresh and try again."), a duplicate application, or a duplicate job ID.

## Core components

### Pipeline rules: `stages.py`, `pipeline.py`

- Allowed moves: exactly one stage forward, or to Rejected from any stage before Hired.
- Hired and Rejected are final; any other move raises a clear error.
- Every move sends the stage the screen showed (`expected_stage`). If it is stale, the move is refused, so a double-click can never skip a stage. The check and the insert happen in one `BEGIN IMMEDIATE` transaction.
- An application needs a name, a valid email, an existing job ID and a resume. The same email can apply to different jobs, but not twice to the same one.
- Recording a rating appends a `rated` event and never changes the stage.

### Audit trail: `store.py`

- Nothing is edited in place. Every action (candidate added, advanced, rejected, rated) is a new row in an `events` table. A candidate's name, application, current stage, time in stage and latest rating are computed from these rows.
- The store exposes only append; SQLite triggers reject any `UPDATE` or `DELETE` on the table.
- Each row stores the SHA-256 hash of the previous row and its own hash, so hand-editing the database file is detected by `/api/audit/verify`.
- The application event records the resume's SHA-256 hash, so the resume a rating was based on can never be silently swapped.
- A separate `jobs` table holds job descriptions. It is reference data, prefilled with JOB-001 and extended from the Job portal page. Each rating event keeps its own copy of the requirements it was judged against.

### Search: `search/`

The recruiter never types syntax. The search box is a typo-tolerant name search, and everything else is a filter chosen from the **Filters** panel. All of them combine with AND.

| Recruiter's question | How she asks it |
| --- | --- |
| Find Priya Sharma (typed "sharam") | Search box: `sharam` |
| Who's in Interview right now? | Current stage: Interview |
| Stuck in Screening for more than a week | Current stage: Screening · Time in current stage: More than a week |
| Moved to Interview since Monday | Reached stage: Interview · When: Since Monday |
| Reached Screening before Monday / on one day | Reached stage: Screening · When: Before Monday / On Yesterday |
| Never made it to Interview | Never reached: Interview |
| Reached Offer but didn't get hired | Reached stage: Offer · Exclude stage: Hired |
| Everyone except rejected candidates | Exclude stage: Rejected |
| Applicants for one job | Job: JOB-001 |
| Combined example | Search box: `priya` · Current stage: Interview and Offer |

Filters: current stage (any of several), excluded stages, time in current stage (more than / less than N days), stage reached (optionally since, before or on today, yesterday, a weekday, a date, or N days ago), a stage never reached, and job. Above the results, a line always says exactly what was searched, in plain English. "Monday" and "today" are resolved in the recruiter's time zone, IST by default.

- **`filters.py`** turns the filters into a query tree (`to_tree`) and back (`from_tree`, used for AI translations). `from_tree` puts every condition that fits a menu into the menus; anything left (OR across different filters, a second "reached", NOT on a job) goes into an `advanced` field, which runs like any other filter and shows as its own chip in plain English. So every valid query can be run and shown. It rejects filters that can't work together before searching: a stage that is both chosen and excluded, reached and never reached the same stage, a date without a stage, "on" with a moment instead of a day, "more than 7 days" and "less than 3 days" together.
- **`parser.py`** is internal. It reads the query strings DeepSeek writes and the evals' expected answers; recruiters never see it.
- **Fuzzy matching:** optimal string alignment distance, which counts swapped adjacent letters as one typo, so "sharam" is one step from "sharma". Words of up to 3 letters must match exactly, 4 to 7 letters allow one typo, 8 or more allow two. Exact and prefix matches score highest. Filler words around a name ("find", "show me") are ignored.
- **Ranking:** name similarity first. For filter-only searches, the most relevant signal: the most recent move for a "since" filter, otherwise the longest time in the current stage.
- **Explained empty results** (`evaluate.py` with `describe.py`), always in plain English: which filter nobody matches ("Nobody has applied for JOB-002."), or which one ruled out the rest ("Only 1 candidate is currently in Offer, and it's not someone who has been in their current stage for less than 1 day."). A question typed in the name box is pointed at the right filter ("The search box only looks for names. To see who is in Interview, open Filters and choose it under Current stage.").

### Frontend: `static/`

- **`index.html`:** name search box, a **Filters** button with a count of active filters, removable chips for each applied filter, the collapsible filters panel (current stage, excluded stage, time in stage, job, stage reached with since / before / on a day, never reached), a "Showing candidates who…" line above the results, the pipeline board (one column per stage), ranked search results, the add-candidate dialog, and a slide-in candidate panel with the rating card, the job's requirements beside the candidate's details, the history timeline, the resume viewer, and only the valid actions.
- **`app.js`:** a small `api()` helper around `fetch` that turns error JSON into readable messages; renders the board, results and panel; debounced search as you type and on every filter change (never AI); `Enter` sends the text and current filters to `/api/assist`, and fills the filters panel with what comes back; polls the rating while it runs; re-fetches after every action.
- **`jobs.html`:** the Job portal, a plain sheet of jobs with an empty row at the bottom for adding one.
- **`styles.css`:** dark theme; board columns, cards, panel, rating card and sheet; works on smaller screens.

## The AI layer

The AI layer adds two features: asking search questions in plain English, and rating how well each candidate matches the job's requirements.

### The two models do different jobs

| | DeepSeek | Jev (TypeSafe) |
| --- | --- | --- |
| What it is | A text-generation LLM with an OpenAI-compatible API | A "System One" decision model. It cannot write text; it returns typed answers with probabilities |
| Output | Free text or JSON | Choice (one option from a list), Score (a position on an ordered rubric), or Noul (probability a statement is true) |
| Role in Recruitly | Translates English questions into query syntax; extracts facts from resumes | Routes search input, checks translations, rates candidates per category |
| Trusted? | Never directly; output is validated by our code | As a signal; our code decides what to do with it |

**Guiding rule: DeepSeek writes, Jev judges, and our code decides and enforces.** Policy (what is allowed, what gets recorded, how the overall rating is calculated) always lives in our code.

### Applications: job, requirements and resume

Rating a candidate needs something to rate against, so every application is linked to a job with defined requirements, and carries a resume.

**Job** (prefilled example: JOB-001; more are added on the Job portal page)

| Field | JOB-001 |
| --- | --- |
| Job ID and title | JOB-001 · Backend Engineer |
| Minimum experience | 3 years |
| Required skills | Python, FastAPI, SQL, REST API design |
| Nice-to-have skills | Docker, AWS, Redis |
| Budget (CTC per annum) | ₹18,00,000 to ₹26,00,000 (18 to 26 LPA) |
| Location / work mode | Lucknow · Hybrid |

**Application**

- Name, email, job ID applied for, expected CTC (optional; needed for the budget rating, since resumes rarely include it), and a resume PDF (required, up to 5 MB and 10 pages).
- The recruiter types the job ID; the portal fetches that job from the database and shows its requirements before saving.
- All recorded in the application (`added`) event, including the resume's SHA-256 hash.

**Read-only resume viewer**

- On upload, the server extracts the text (for AI) and renders each page to an image. The original PDF is stored outside the web folder, filed by its hash, and never served; the profile shows only the page images.
- There is no download link or file URL, and page images are sent with no-store headers. Dragging and the right-click menu are disabled on them.
- Honest limit: anything shown on screen can still be screenshotted. This prevents casual downloading, not determined copying.

### The candidate profile shows

- Pipeline stage, time in stage, and the valid actions.
- The match rating card (when AI is configured): a **Create candidate rating** button; then each category out of 5 with its weight and evidence, the overall rating out of 10, anything that was dropped, the model versions, and a "needs review" flag if Jev was unsure.
- The job applied for, with its requirements next to the candidate's matching facts.
- The full history.
- The resume viewer.

## Feature 1: ask in plain English

The recruiter can type a question like "who's been sitting in screening forever?" instead of choosing Current stage: Screening and More than a week. The answer comes back as those same filters, filled in so she can see and adjust them. Name searches still run instantly, as she types, with no AI.

```mermaid
flowchart TD
    A["Recruiter presses Enter"] --> P{"Do the words match<br/>a candidate's name?"}
    P -- "yes" --> R["Name search + her filters<br/>instant, no AI"]
    P -- "no" --> J["Jev router: one call<br/>Choice + Noul"]
    J -- "candidate name" --> N["Show the name search"]
    J -- "off-topic, unclear, or on-topic below 0.5" --> T["Template message"]
    J -- "English question" --> D["DeepSeek translates<br/>English → query string"]
    D --> V{"Parser validates, then<br/>converted to portal filters<br/>(leftovers kept as an extra condition)<br/>1 retry with the problem fed back"}
    V -- "still invalid, or UNSUPPORTED" --> C["I couldn't turn that into a search"]
    V -- valid --> S["Describe the filters in English<br/>(code, no AI)"]
    S --> K["Jev check: Noul<br/>does it answer the question?"]
    K -- "probability ≥ 0.7" --> I["Fill in the filters, run,<br/>'Interpreted as: …'"]
    K -- "below 0.7" --> G["Offer the filters<br/>she applies or adjusts them"]
```

If Jev or DeepSeek fails or times out at any point, she gets exactly what the plain search would have given: the name search with her filters, and its explanation.

### Step by step

- **When AI runs.** Only when she presses Enter and the words in the search box match no candidate's name. "sharam" and "priya sharma" never reach the AI; "who got hired last week" does.
- **Jev router.** One request asks two questions: a Choice (`candidate_name`, `english_question`, `off_topic`, `unclear`) and a Noul (is this about candidates in a hiring pipeline?). The router takes the top answer; an on-topic probability below 0.5 overrides it to off-topic. DeepSeek is only called for English questions.
- **DeepSeek translation.** A fixed prompt describes the full query language with examples and today's date, at temperature 0. It must return only a query string, or `UNSUPPORTED` if the question isn't about finding candidates by name, stage, time in stage, when they reached a stage, or job.
- **Validation.** Our parser checks the output and `filters.from_tree` converts it to portal filters, keeping anything no menu can hold as an extra condition. If the parser or the filters reject it, DeepSeek gets one retry with the problem; if it fails again, she is told it couldn't be turned into a search.
- **Describe, then check.** Our code turns the filters that will actually run back into English ("Candidates who have been in Screening for more than 7 days"), and a Jev Noul checks it against her question.
- **Confidence decides the UI.** At or above 0.7, the filters are filled in and run, with "Interpreted as: …" and a link to adjust them. Below, the filters are offered to apply or adjust first. Filters from the AI replace the ones she had applied.

## Feature 2: candidate match rating

Each application is rated against its job's requirements: three categories scored by Jev and one by code, each out of 5, and an overall rating out of 10. A rating runs when the recruiter clicks **Create candidate rating** on the profile; a spinner shows until it finishes, then the rating appears. It can be re-run. The rating is advice for the recruiter; it never moves a candidate.

```mermaid
flowchart TD
    U["Application submitted<br/>resume PDF + job ID + expected CTC"] --> RR["Read resume<br/>extract text, render page images"]
    RR -- images --> VW["Resume viewer<br/>page images only"]
    B["Recruiter clicks<br/>Create candidate rating"] --> X["DeepSeek extracts facts<br/>skills, roles, years + quotes"]
    RR -. "stored text" .-> X
    X --> EV{"Verify evidence<br/>each quote must be in the resume"}
    EV -- "not found" --> DR["Unverified facts dropped<br/>listed on the card"]
    EV -- "facts only, no personal details" --> JS["Jev Score × 3<br/>skills · experience · relevance"]
    BF["Budget fit<br/>expected CTC vs range (code)"] --> OV["Overall rating / 10<br/>weighted average (code)"]
    JS --> OV
    OV -- "confidence below 0.5" --> NR["Needs review flag"]
    OV --> SV["Saved to the audit trail, shown on the profile<br/>advisory only: she decides every move"]
```

### Who does what

- **DeepSeek extracts facts, not opinions.** From the resume text it returns structured JSON: skills found, past roles with dates, stated years of experience, each with a short quote from the resume as evidence. It does not rate anything. Invalid JSON gets one retry.
- **Our code verifies the evidence.** Every quote must actually appear in the resume text (ignoring case, spacing and typographic quotes). Facts without a matching quote are dropped, so an invented skill can't raise a rating. Our code also computes years of experience from the verified role dates, merging overlaps, so the number doesn't depend on a model's arithmetic.
- **Jev rates each category.** Jev's Score type rates a state against ordered rubric levels and returns a probability-weighted position with a confidence value; the code maps its five levels to 1 to 5. All three categories are asked in one request. Jev sees the job requirements and the verified facts only.
- **Budget fit is plain arithmetic.** Expected CTC against the budget range needs no AI.
- **Our code computes the overall rating.** A fixed, visible formula, not a model's opinion.

### Categories and rubrics (each out of 5)

| Category | Rated by | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- | --- |
| Skills | Jev Score | None or only one of the required skills | Some required skills, but fewer than half | About half of the required skills | Most or all required skills, but few or none of the nice-to-haves | All required skills and at least some nice-to-haves |
| Experience | Jev Score | Less than half the required years, or no relevant experience | Below the minimum, but more than half of it | Within a few months of the minimum | More than the minimum in total, but only part of it directly relevant | Exceeds the minimum in directly relevant work |
| Role relevance | Jev Score | Unrelated field, or no roles | Loosely related: technical or adjacent work outside this field | Related field, different kind of role | Same kind of role, different domain or narrower scope | Same kind of role in a similar domain |
| Budget fit | Our code | More than 25% above the budget maximum | 10% to 25% above the maximum | Up to 10% above the maximum | Above the midpoint, within the budget | At or below the budget midpoint |

The full rubric wording lives in `app/ai/questions.py`. Levels 1, 3 and 5 follow the original design; levels 2 and 4 are drafted to sit between them.

### Overall rating out of 10

```
overall = 2 × (0.35·skills + 0.30·experience + 0.20·relevance + 0.15·budget)
# shown to one decimal, e.g. 7.4 / 10
# if a category can't be rated (e.g. no expected CTC), it is left out and the
# remaining weights are rescaled; the card says which category is missing
```

The weights are starting values, kept in `app/ai/weights.py` and shown on the rating card so the recruiter can see how the number was made.

## Guardrails

- **Jev never sees personal details.** No name, email, photo, age, gender, address, salary, resume text or quotes; only the job requirements and verified, job-relevant facts (skill names, role titles, organisations, dates and years). DeepSeek is instructed to extract nothing personal.
- **Advisory only.** A rating never advances, rejects or hires anyone. The board is not sorted by rating, and there is no rating filter.
- **Needs review.** If Jev's confidence on any category is below 0.5, the card says so instead of presenting a shaky number as certain.
- **Auditable.** Each rating is saved as an event with the model versions, the resume hash, the requirements used, the verified facts, the weights and the threshold. Re-rating adds a new event; old ratings are never overwritten. Failed attempts are recorded too.
- **Pinned model.** The Jev model version is pinned (`jev-1.13.0`) rather than using the moving `jev-latest` alias, so scores and confidence values don't shift between releases and thresholds stay valid.
- **Legal context.** Automated candidate scoring is regulated in some places (for example, New York City's bias-audit rules for automated hiring tools, and the EU AI Act's treatment of recruitment AI as high-risk). A production version would need a bias audit.

## Questions and thresholds

Following TypeSafe's guidance, every Jev question, option list, rubric and threshold lives in `app/ai/questions.py`, to be edited by hand. Question IDs are for our code and are not sent to the model.

| ID | Type | Question | How the answer is used |
| --- | --- | --- | --- |
| `input_kind` | Choice | What kind of input is the search text? Options: candidate name, question in English, off-topic, unclear | Top answer picks the path; no threshold |
| `on_topic` | Noul | Is the input an attempt to find or filter candidates in a hiring pipeline? | Below 0.5 → off-topic message |
| `translation_ok` | Noul | Would the described search return the candidates the recruiter asked for? | At or above 0.7 → apply the filters; else suggest them (to be tuned with evals) |
| `skills_match` | Score | How well do the candidate's verified skills cover the job's required and nice-to-have skills? (5 levels) | Category score; confidence below 0.5 → needs review |
| `experience_match` | Score | How does the candidate's relevant experience compare with the job's minimum? (5 levels) | Category score; confidence below 0.5 → needs review |
| `role_relevance` | Score | How relevant are the candidate's past roles to this job? (5 levels) | Category score; confidence below 0.5 → needs review |

## Failure handling

| Situation | What the recruiter sees |
| --- | --- |
| No API keys configured | AI features hidden; resumes still viewable; the app works normally |
| Resume is a scanned image with no text | "Couldn't read text from this resume; rating unavailable"; the resume can still be viewed |
| DeepSeek returns invalid JSON twice, or doesn't answer | "Rating failed: …" with the **Create candidate rating** button to try again |
| Jev doesn't answer, or its reply is incomplete | "Rating failed: The scoring service did not answer." with the button to try again |
| No expected CTC given | Budget fit shown as "Not rated"; the overall uses the other categories |
| Jev unsure on a category | Score shown with a "needs review" flag |
| Search AI times out or errors | The name search with her filters, and its explanation; the page never blocks |
| Low-confidence search translation | The filters offered to apply or adjust first |
| Question that isn't about candidates, or no valid query after the retry | "I couldn't turn that into a search. Try rephrasing it, or choose what you need under Filters." |

## Privacy

- Plain-English search sends only her question text (and today's date, and the English description of the translated filters), never candidate records.
- Rating sends the resume text to DeepSeek for fact extraction; that text includes the candidate's personal details. Jev receives only the job requirements and verified, job-relevant facts, with no personal details.
- Original resume files stay on the server and are never served.

## Evaluation

- **Search eval** (`evals/search_eval.py`): 30 English questions with expected queries. A translation counts as correct when the filters it produces find the same candidates in the demo data as the expected query. Reports accuracy and how many were run automatically versus suggested.
- **Rating eval** (`evals/rating_eval.py`): the 14 made-up demo resumes with expected category scores, reported as agreement within ±1 point per category. The expected scores are a first draft to be reviewed by a person.
- **Fairness check:** the same resume rated under a different name must get the same rating. Because Jev never sees the name, this should hold by design; the rating eval checks it against the live models.
- **Consistency check:** rating the same resume twice should give the same result; checked by the rating eval.

The evals call the live models and have not been run yet.

## Project layout

```
Recruitly/
├── app/
│   ├── main.py            # FastAPI app, routes, serves static/
│   ├── schemas.py         # Pydantic request/response models
│   ├── config.py          # settings from the environment and .env
│   ├── stages.py          # stages + allowed moves
│   ├── pipeline.py        # add / advance / reject / record a rating
│   ├── store.py           # SQLite event store, hash chain, jobs table
│   ├── jobs.py            # Job type and the prefilled jobs
│   ├── seed.py            # demo candidates and their made-up resumes
│   ├── search/
│   │   ├── filters.py     # portal filters ⇄ query tree; catches impossible combinations
│   │   ├── evaluate.py    # matching + ranking + empty-result explanations
│   │   ├── describe.py    # query tree → plain English (no AI)
│   │   ├── fuzzy.py
│   │   ├── lexer.py       # internal: reads DeepSeek's query strings
│   │   └── parser.py
│   ├── resumes/
│   │   ├── storage.py     # store PDF by hash, outside the web folder
│   │   ├── render.py      # extract text + render page images (pypdfium2)
│   │   └── simple_pdf.py  # writes the synthetic resume PDFs for the demo data and evals
│   └── ai/
│       ├── questions.py   # every Jev question, rubric and threshold
│       ├── weights.py     # overall-rating weights
│       ├── jev.py         # Jev client: router, translation check, category scores
│       ├── deepseek.py    # query translation + resume fact extraction
│       ├── evidence.py    # checks each extracted quote exists in the resume
│       ├── rating.py      # orchestrates the rating flow, computes the overall
│       ├── assist.py      # plain-English search → portal filters
│       └── messages.py    # templates for off-topic / unclear / low confidence / rating status
├── static/
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   └── jobs.html          # the Job portal
├── evals/                 # search_eval.py, rating_eval.py: call the live models
├── docs/
│   └── ARCHITECTURE.md
├── requirements.txt
└── README.md
```

## Configuration

Settings are read from the environment, or from a `.env` file in the project root:

```
DEEPSEEK_API_KEY=                 # optional
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
TYPESAFE_API_KEY=                 # optional; JEV_API_KEY is accepted too
JEV_MODEL=jev-1.13.0
# RECRUITLY_AI=off                # disable the AI layer even when keys are present
```

Both keys are needed for either AI feature. `RECRUITLY_DB` sets the database path (default `data/recruitly.db`); resumes are stored in a `resumes` folder beside it.

## Build order

| Step | Work | Done when | Status |
| --- | --- | --- | --- |
| 1 | Stages, pipeline rules, event store | Stage rules enforced; tampering detected | Done |
| 2 | Search engine | All six brief examples work, errors explained | Done |
| 3 | FastAPI routes + demo seed | Endpoints work; docs visible at `/docs` | Done |
| 4 | Frontend | Board, search and candidate panel work end to end | Done |
| 5 | Jobs, application fields, resume storage and read-only viewer | Upload, viewer and job lookup work without AI | Done |
| 6 | `questions.py` and `weights.py`, with hand-edited wording | First draft written; hand editing pending | Drafted |
| 7 | Rating: fact extraction, evidence check, Jev scores, overall; profile rating card | Rating card works end to end | Done; not yet run against the live models |
| 8 | Plain-English search: router, translation, check, `/api/assist`, UI | Every path in the flow works | Done; not yet run against the live models |
| 9 | Evals (search, rating, fairness, consistency); record results in the README | Results recorded | Written; not yet run |
| 10 | README | How to run, decisions, limits and roadmap documented | Done |

## Changes from the original design

| Original design | What was built, and why |
| --- | --- |
| Ratings run automatically when a candidate is added | Ratings run when the recruiter clicks **Create candidate rating**, with a spinner until done. Requested so the recruiter decides when models are called |
| Jobs are seeded only | A jobs table prefilled with JOB-001, plus a Job portal page for adding jobs (add only, no editing) |
| The search language gains `rating:` and `job:` filters | Only a Job filter was added. There is no filtering on ratings |
| Recruiters type a query language (`stage:screening for:>7d`), with a filters panel that writes it | The query language is hidden. Recruiters use a name box and filters, including "never reached" and since / before / on a day. The syntax is only used internally for AI translations and evals. OR across different filters has no menu; it is reachable by asking in plain English and shows as its own chip |
| The router's Choice runs only after the parser rejects input or words match no name | It runs when the typed words match no name. There is no "query typo" option any more, since nothing is typed in the syntax |
| DeepSeek returns only a query string | Same, plus it may return `UNSUPPORTED` when the question isn't a candidate search |
| Jev's key named `TYPESAFE_API_KEY` | `JEV_API_KEY` is accepted as well |
| Years of experience come from DeepSeek | Also computed in code from the verified role dates, and both are shown |
| Only successful ratings are saved | Failed attempts are recorded as well, so "Rating failed" survives a restart |
