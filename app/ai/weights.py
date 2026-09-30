"""Overall rating weights: overall = 2 x weighted average, out of 10.
Unrated categories are dropped and the rest rescaled."""

WEIGHTS = {
    "skills": 0.35,
    "experience": 0.30,
    "relevance": 0.20,
    "budget": 0.15,
}

LABELS = {
    "skills": "Skills",
    "experience": "Experience",
    "relevance": "Role relevance",
    "budget": "Budget fit",
}
