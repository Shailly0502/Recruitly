"""User-facing messages for search and rating."""

OFF_TOPIC = (
    "This box only searches candidates. Try a name, or a question like "
    "\"who has been in screening for more than a week?\""
)
UNCLEAR = (
    "I couldn't tell what you're looking for. Try a candidate's name, a question about "
    "candidates, or choose what you need under Filters."
)
COULD_NOT_INTERPRET = "I couldn't turn that into a search. Try rephrasing it, or choose what you need under Filters."
LOW_CONFIDENCE = "I'm not sure this is what you meant. Apply these filters, or adjust them first."
INTERPRETED = "Interpreted as: {description}"

RATING_UNREADABLE = "Couldn't read text from this resume; rating unavailable"
RATING_NO_RESUME = "No resume on file; rating unavailable"
RATING_AI_OFF = "AI rating is not configured"
RATING_NOT_RATED = "Not rated yet"
RATING_PENDING = "Rating in progress"
RATING_FAILED = "Rating failed"
