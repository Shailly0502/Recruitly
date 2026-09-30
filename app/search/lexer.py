"""Tokenizer. Tracks positions so errors can point at the problem."""

from dataclasses import dataclass

LPAREN = "("
RPAREN = ")"
NOT = "NOT"
OR = "OR"
AND = "AND"
WORD = "WORD"      # a bare word or a field:value filter
PHRASE = "PHRASE"  # "quoted text"


class QueryError(Exception):
    """Unparseable query. `position` is the character offset of the problem."""

    def __init__(self, message: str, position: int = 0):
        super().__init__(message)
        self.message = message
        self.position = position


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    start: int
    end: int


def tokenize(query: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    while i < len(query):
        ch = query[i]
        if ch.isspace():
            i += 1
        elif ch in "()":
            tokens.append(Token(LPAREN if ch == "(" else RPAREN, ch, i, i + 1))
            i += 1
        elif ch == '"':
            close = query.find('"', i + 1)
            if close == -1:
                raise QueryError('This quote is never closed. Add a closing ".', i)
            tokens.append(Token(PHRASE, query[i + 1:close], i, close + 1))
            i = close + 1
        elif ch == "-":
            if i + 1 >= len(query) or query[i + 1].isspace() or query[i + 1] == ")":
                raise QueryError("'-' must be followed by what to exclude, like -stage:rejected.", i)
            tokens.append(Token(NOT, ch, i, i + 1))
            i += 1
        else:
            end = i
            while end < len(query) and not query[end].isspace() and query[end] not in '()"':
                end += 1
            text = query[i:end]
            keyword = text.upper() if text.upper() in (OR, AND, NOT) else WORD
            tokens.append(Token(keyword, text, i, end))
            i = end
    return tokens
