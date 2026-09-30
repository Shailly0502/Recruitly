"""DeepSeek client: English -> query, resume -> facts. Its output is always
validated elsewhere (parser, evidence check)."""

import json
from datetime import datetime

import httpx2

SEARCH_TIMEOUT = 10.0
RATING_TIMEOUT = 60.0
UNSUPPORTED = "UNSUPPORTED"
MAX_RESUME_CHARS = 20_000


class DeepSeekError(Exception):
    pass


class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def complete(self, system: str, user: str, *, json_mode: bool = False, timeout: float) -> str:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            response = httpx2.post(self._url, json=body, headers=self._headers, timeout=timeout)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"] or ""
        except (httpx2.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise DeepSeekError(f"DeepSeek request failed: {type(error).__name__}") from error


# ---- English question -> query string ---------------------------------------

TRANSLATE_PROMPT = f"""You translate a recruiter's question into the search syntax of a hiring portal.
Reply with the query string only: one line, no explanation, no quotes, no code block.

Candidates move through the stages applied, screening, interview, offer, hired.
A candidate can also be rejected from any stage before hired. hired and rejected are final.

Syntax:
  word                     a candidate's name (typos are tolerated)
  stage:STAGE              is in that stage now (applied, screening, interview, offer, hired, rejected)
  for:>DURATION            has been in the current stage longer than DURATION; also <, >=, <=
  reached:STAGE            entered that stage at some point
  reached:STAGE>=DATE      entered that stage on or after DATE; also >, <, <=, =
  job:ID                   applied for that job, e.g. job:JOB-001
  A space between terms means AND. OR must be written in capitals. A leading - means NOT.
  Parentheses group terms.

DURATION is a number and a unit with no space: 12h, 7d, 2w.
DATE is one of: today, yesterday, a weekday name (the most recent one, counting today),
a date as YYYY-MM-DD, or a DURATION meaning that long ago (reached:offer>=30d).
There are no spaces inside a term.

Examples:
  who is in interview right now?                      -> stage:interview
  who has been stuck in screening for over a week?    -> stage:screening for:>7d
  who moved to interview since monday?                -> reached:interview>=monday
  who reached offer but didn't get hired?             -> reached:offer -stage:hired
  everyone except rejected candidates                 -> -stage:rejected
  is priya in interview or offer?                     -> (stage:interview OR stage:offer) priya
  who got hired in the last 30 days?                  -> reached:hired>=30d
  who was rejected yesterday?                         -> reached:rejected=yesterday
  JOB-001 applicants still waiting in applied         -> job:JOB-001 stage:applied

If the question cannot be expressed in this syntax, reply with exactly {UNSUPPORTED}."""


def translate(client, question: str, today: datetime, failed: tuple[str, str] | None = None) -> str:
    """`failed` is (query, parser error) from the previous attempt."""
    user = f"Today is {today:%A %Y-%m-%d}.\nQuestion: {question}"
    if failed:
        user += (f"\n\nYour previous answer was: {failed[0]}\n"
                 f"The portal rejected it: {failed[1]}\nReply with a corrected query string only.")
    reply = client.complete(TRANSLATE_PROMPT, user, timeout=SEARCH_TIMEOUT)
    lines = [line.strip().strip("`").strip() for line in reply.strip().splitlines()]
    lines = [line for line in lines if line and not line.lower().startswith(("```", "json", "text"))]
    return lines[0][:300] if lines else ""


# ---- resume text -> facts with evidence -------------------------------------

EXTRACT_PROMPT = """You extract job-relevant facts from a resume. You do not judge or rate the candidate.

Reply with one JSON object and nothing else, in this shape:
{
  "skills": [{"name": "Python", "quote": "..."}],
  "roles": [{"title": "Backend Engineer", "organization": "Acme", "start": "2021-03", "end": "present", "quote": "..."}],
  "experience": {"years": 4.5, "quote": "..."}
}

Rules:
- "quote" is a short passage copied from the resume exactly, character for character, at most
  200 characters, that shows the fact. Do not paraphrase, join separate passages, or fix typos.
- skills: technical and professional skills the resume states. One entry per skill.
- roles: paid or professional positions. "start" and "end" are YYYY-MM or YYYY; "end" is
  "present" for a current role. Use null for a date the resume does not give.
- experience: total years of professional experience, only if the resume states a number.
  Otherwise use null for "experience".
- Leave out anything the resume does not say. Use an empty list when there is nothing.
- Never include the person's name, email, phone number, address, age, date of birth, gender,
  nationality, marital status, photo or any other personal detail."""


def extract_facts(client, resume_text: str) -> dict:
    """Retries once on invalid JSON, then raises DeepSeekError."""
    user = "Resume:\n" + resume_text[:MAX_RESUME_CHARS]
    for _ in range(2):
        reply = client.complete(EXTRACT_PROMPT, user, json_mode=True, timeout=RATING_TIMEOUT)
        try:
            facts = json.loads(reply)
        except ValueError:
            continue
        if isinstance(facts, dict):
            return facts
    raise DeepSeekError("DeepSeek did not return valid JSON.")
