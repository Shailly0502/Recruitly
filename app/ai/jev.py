"""Jev (TypeSafe) client. Returns typed answers; callers decide what to do with them.
The helpers take anything with an `ask` method."""

from dataclasses import dataclass

from . import questions

SEARCH_TIMEOUT = 8.0   # seconds
RATING_TIMEOUT = 30.0


class JevError(Exception):
    pass


@dataclass(frozen=True)
class JevResult:
    model: str     # model version that answered
    answers: dict  # question id -> answer dict


class JevClient:
    def __init__(self, api_key: str, model: str):
        from typesafe_sdk import TypeSafeClient
        self.model = model
        self._client = TypeSafeClient(api_key=api_key, model=model)

    def ask(self, state: dict, questions: dict, timeout: float) -> JevResult:
        from typesafe_sdk import TypeSafeError
        try:
            response = self._client.system_one(state, questions, timeout=timeout)
        except TypeSafeError as error:
            raise JevError(str(error)) from error
        return JevResult(response.model, {name: answer.model_dump() for name, answer in response.answers.items()})


@dataclass(frozen=True)
class Route:
    kind: str        # candidate_name | english_question | off_topic | unclear
    on_topic: float  # P(input is about candidates)


def route(jev, search_input: str) -> Route:
    """Both router questions in one request."""
    state = {"context": questions.ROUTER_CONTEXT, "search_input": search_input}
    answers = jev.ask(state, questions.ROUTER_QUESTIONS, SEARCH_TIMEOUT).answers
    return Route(kind=_field(answers, "input_kind", "choice"), on_topic=_field(answers, "on_topic", "noul"))


def translation_ok(jev, recruiter_question: str, search_description: str) -> float:
    """P(the described search answers the question)."""
    state = {"recruiter_question": recruiter_question, "search_description": search_description}
    answers = jev.ask(state, questions.CHECK_QUESTIONS, SEARCH_TIMEOUT).answers
    return _field(answers, "translation_ok", "noul")


@dataclass(frozen=True)
class CategoryScore:
    score: float       # 1 to 5
    confidence: float  # 0 to 1


def score_categories(jev, job: dict, candidate: dict) -> tuple[dict[str, CategoryScore], str]:
    """Scores all three categories in one request. `candidate` must hold verified facts only."""
    asked = {question_id: question for question_id, question in questions.RATING_QUESTIONS.values()}
    result = jev.ask({"job": job, "candidate": candidate}, asked, RATING_TIMEOUT)
    scores = {}
    for category, (question_id, question) in questions.RATING_QUESTIONS.items():
        position = _field(result.answers, question_id, "score")  # 0 .. levels-1
        top = len(question["criteria"]) - 1
        scores[category] = CategoryScore(
            score=1 + 4 * min(max(position, 0), top) / top,
            confidence=_field(result.answers, question_id, "confidence"),
        )
    return scores, result.model


def _field(answers: dict, question_id: str, field: str):
    try:
        return answers[question_id][field]
    except (KeyError, TypeError):
        raise JevError(f"Jev's reply has no '{field}' for '{question_id}'.") from None
