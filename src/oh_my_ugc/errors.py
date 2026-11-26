"""Errors that carry a plain-English sentence safe to show to a user."""

from __future__ import annotations


class OmuError(Exception):
    """A failure with a message written for people (one sentence, says what to do next)."""

    def __init__(self, message: str, *, detail: str = "", status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.status = status


MAX_NAME = 120
MAX_TEXT = 20_000


def check_lengths(values: dict, names: tuple[str, ...] = ("name",)) -> None:
    """Names up to 120 characters, every other text field up to 20,000 (a plain sentence if too long)."""
    for key, value in values.items():
        if isinstance(value, str):
            limit = MAX_NAME if key in names else MAX_TEXT
            if len(value) > limit:
                what = key.replace("_", " ")
                raise OmuError(f"The {what} is too long. Keep it under {limit:,} characters.")


class OutOfCredit(OmuError):
    pass


class BudgetExceeded(OmuError):
    pass


class NotFound(OmuError):
    def __init__(self, what: str) -> None:
        super().__init__(f"{what} was not found.", status=404)
