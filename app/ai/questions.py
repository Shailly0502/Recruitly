"""Jev questions, rubrics and thresholds. Edit wording here and rerun the evals.

Backticked names in `instructions` refer to fields in the state. Score criteria
run lowest to highest; Jev returns a position from 0. Question IDs aren't sent.
"""

# ---- thresholds -------------------------------------------------------------

# At or above: apply the translated filters. Below: suggest them. Tune with the evals.
TRANSLATION_OK_THRESHOLD = 0.7

# Below this, the input is treated as off-topic.
ON_TOPIC_THRESHOLD = 0.5

# Category confidence below this gets "needs review" (TypeSafe's low-confidence line).
NEEDS_REVIEW_CONFIDENCE = 0.5


# ---- search: what did the recruiter type? -----------------------------------

ROUTER_CONTEXT = (
    "A recruiter typed `search_input` into the search box of a hiring pipeline portal. "
    "The box searches candidate names, and also accepts questions in plain English about "
    "candidates. Stages, time in stage, dates and jobs are otherwise chosen from filter menus. "
    "The stages are applied, screening, interview, offer, hired and rejected."
)

INPUT_KIND = {
    "type": "choice",
    "instructions": "What kind of input is `search_input`?",
    "criteria": {
        "candidate_name": (
            "A person's name or part of one, possibly misspelled, with no question or "
            "instruction around it."
        ),
        "english_question": (
            "A question or request in ordinary English about which candidates are in the "
            "pipeline: their stage, how long they have waited, when they moved, or their outcome."
        ),
        "off_topic": (
            "Readable text that has nothing to do with finding candidates: general knowledge, "
            "small talk, or a request to do something other than search."
        ),
        "unclear": (
            "Too garbled, fragmentary or ambiguous to tell what the recruiter is looking for."
        ),
    },
}

ON_TOPIC = {
    "type": "noul",
    "instructions": "Is `search_input` an attempt to find or filter candidates in a hiring pipeline?",
    "criteria": {
        "true": "It names a candidate, or asks about candidates, stages or hiring outcomes.",
        "false": "It is about something else, or asks the portal to do something other than search.",
    },
}


# ---- search: does the translation answer the question? ----------------------

TRANSLATION_OK = {
    "type": "noul",
    "instructions": (
        "Would the search described in `search_description` return the candidates the "
        "recruiter asked for in `recruiter_question`?"
    ),
    "criteria": {
        "true": (
            "The description covers every condition in the question (stage, time span, "
            "outcome, names, exclusions) and adds none the question does not imply."
        ),
        "false": (
            "The description misses a condition, adds one that was not asked for, or gets "
            "a stage, time span or exclusion wrong."
        ),
    },
}


# ---- rating: three categories, each on five levels --------------------------
# Levels 1, 3 and 5 are from the design doc; 2 and 4 sit between them.

SKILLS_MATCH = {
    "type": "score",
    "instructions": (
        "How well do the skills in `candidate.skills` cover `job.required_skills` and "
        "`job.nice_to_have_skills`? Count a skill as covered when the candidate lists it or "
        "an obvious equivalent (for example PostgreSQL covers SQL)."
    ),
    "criteria": [
        "The candidate has none or only one of the required skills.",
        "The candidate has some of the required skills, but fewer than half.",
        "The candidate has about half of the required skills.",
        "The candidate has most or all of the required skills, but few or none of the nice-to-have skills.",
        "The candidate has all of the required skills and at least some of the nice-to-have skills.",
    ],
}

EXPERIENCE_MATCH = {
    "type": "score",
    "instructions": (
        "How does the candidate's experience in `candidate.experience` and `candidate.roles` "
        "compare with `job.min_experience_years`? Judge the amount of experience in work "
        "relevant to `job.title`."
    ),
    "criteria": [
        "Well below the minimum: less than half the required years, or no relevant experience.",
        "Below the minimum, but more than half the required years.",
        "Roughly meets the minimum: within a few months of the required years.",
        "More than the minimum in total, but only part of it is in directly relevant work.",
        "Exceeds the minimum, and the years are in directly relevant work.",
    ],
}

ROLE_RELEVANCE = {
    "type": "score",
    "instructions": (
        "How relevant are the past roles in `candidate.roles` to a job titled `job.title` "
        "that needs `job.required_skills`?"
    ),
    "criteria": [
        "The roles are in an unrelated field, or there are no roles.",
        "The roles are only loosely related: some technical or adjacent work, outside this job's field.",
        "The roles are in a related field, but are a different kind of role.",
        "The roles are the same kind of role, in a different domain or at a narrower scope.",
        "The roles are the same kind of role in a similar domain.",
    ],
}

ROUTER_QUESTIONS = {"input_kind": INPUT_KIND, "on_topic": ON_TOPIC}
CHECK_QUESTIONS = {"translation_ok": TRANSLATION_OK}

# category -> (question id, question)
RATING_QUESTIONS = {
    "skills": ("skills_match", SKILLS_MATCH),
    "experience": ("experience_match", EXPERIENCE_MATCH),
    "relevance": ("role_relevance", ROLE_RELEVANCE),
}
