# Recruitly

A small applicant-tracking app for running one hiring pipeline: a stage board, a tamper-proof history for every candidate, and a single search box that understands questions like *"stuck in screening for more than a week"*.

> **Status: in development.** This README describes the target design. The [roadmap](#roadmap) shows what is built so far.

## What it does

**Pipeline**

- Add candidates and see everyone grouped by current stage.
- Move a candidate forward one stage at a time: Applied → Screening → Interview → Offer → Hired.
- Reject a candidate from any stage before Hired.
- Hired and Rejected are final. Skipping a stage or undoing a final outcome is refused by the server, not just hidden in the UI.
- Open a candidate to see their full history and how long they have been in their current stage.

**Audit trail**

Every change is recorded as an event that can never be edited or deleted. A candidate's current stage is not stored separately; it is derived from their events, so the history and the board cannot disagree.

**Search**

One search box answers questions about names, current stage, time in stage, past movement, and exclusions:

| The recruiter types | What it means |
| --- | --- |
| `sharam` | Name close to "sharam", so Priya **Sharma** is found despite the typo |
| `in interview` | Current stage is Interview |
| `stuck in screening for more than a week` | Current stage is Screening, entered more than 7 days ago |
| `moved to interview since monday` | Entered Interview on or after the most recent Monday |
| `reached offer but not hired` | Was in Offer at some point, and is not Hired now |
| `everyone except rejected` | Anyone whose current state is not Rejected |

Conditions can be combined (`priya in interview since monday`). Results are ranked, with the closest matches first.

When a query cannot be understood, the app says why instead of showing an empty list:

```
> in interveiw
Unknown stage "interveiw". Did you mean "interview"?

> stuck in screening for more than banana
Expected a duration after "more than", such as "3 days" or "a week".

> hired and rejected
No candidate can be both Hired and Rejected. These are final, separate outcomes.
```

## Architecture

```
  Browser (React)
     │  JSON over HTTP
     ▼
  API (Express)
     │
     ├── Pipeline rules     which moves are allowed from which stage
     ├── Search             text → parsed query → filter → rank
     │
     ▼
  SQLite
     ├── candidates         identity only (name, email, created)
     └── events             append-only; one row per stage change
```

- **Pipeline rules** are one pure module: given a current stage and a requested move, it returns the new stage or a reason for refusing. The API calls it on every write, and it has no database or HTTP dependencies, so it is tested directly.
- **Search** runs in three steps. A parser turns the text into a structured query or an error with a message. A filter selects candidates that satisfy it. A ranker orders them. Each step is tested on its own.
- **Events** are the source of truth. Questions about the past ("reached Offer", "moved since Monday") are answered from the same rows that make up the audit trail.

## Tech stack

| Layer | Choice |
| --- | --- |
| Frontend | React, TypeScript, Vite |
| Backend | Node.js, Express, TypeScript |
| Storage | SQLite |
| Tests | Vitest |

## Running it

Requires Node.js 20 or newer.

```bash
git clone https://github.com/Shailly0502/Recruitly.git
cd Recruitly
npm install
npm run dev      # API and web app, with sample candidates loaded
npm test         # pipeline rules and search tests
```

The terminal prints the local URL to open.

## Decisions and why

**Events are the source of truth, and the database enforces that they are append-only.**
The requirement is that history can never be altered. Storing a `current_stage` column alongside a history table allows the two to drift apart. Instead, the stage is derived from events, and SQLite triggers reject any `UPDATE` or `DELETE` on the events table. The guarantee holds even for code that bypasses the API.

**Rejected is an outcome, not a stage.**
A rejected candidate keeps the stage they were rejected from. This is what makes "reached Offer but didn't get hired" answerable, and it lets the board show where people dropped out.

**The search parser is rule-based, not an LLM.**
The set of questions is small and well defined. A hand-written parser gives the same answer every time, runs instantly with no API key, can be tested exhaustively, and can explain exactly which word it did not understand. An LLM would handle looser phrasing, at the cost of all four.

**Typo tolerance uses Damerau–Levenshtein distance.**
"sharam" for "sharma" is two letters swapped. Plain Levenshtein counts that as two edits; Damerau–Levenshtein counts it as one, which matches how people actually mistype names.

**Ranking is explicit.**
Exact name matches come first, then prefix matches, then fuzzy matches by distance. For queries with no name, candidates who have waited longest in their current stage come first, since they are the ones most likely to need attention.

**"Since Monday" means the most recent Monday at 00:00 in the recruiter's time zone.**
If today is Monday, it means today. Relative dates are resolved on the server using a time zone sent by the browser, so results do not shift at UTC midnight.

**SQLite, with search done in application code.**
One job's worth of candidates fits in memory. This keeps setup to `npm install` and keeps the search logic in one testable place. It is the first thing to change at larger scale (see below).

## With more time

- Multiple jobs, and multiple recruiters with sign-in; record who made each change.
- Notes and attachments on candidates, recorded as events.
- Move filtering into SQL and add a trigram index for fuzzy names once candidates number in the tens of thousands.
- Saved searches, and autocomplete in the search box that shows how the query is being interpreted as it is typed.
- Drag and drop on the board.
- End-to-end browser tests.

## Built with AI assistance

This project was built with Claude Code. The full chat logs are in [`ai-logs/`](ai-logs/).

**A place I disagreed with the AI:** _to be written once the build is done._

## Roadmap

- [ ] Pipeline rules and event store
- [ ] API: add, advance, reject, fetch history
- [ ] Board and candidate detail page
- [ ] Search parser with error messages
- [ ] Fuzzy name matching and ranking
- [ ] Sample data and tests
