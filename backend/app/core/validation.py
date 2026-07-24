"""Shared input-validation guards (S8 hardening).

Rejects control characters and null bytes in user-supplied strings so adversarial input
(null-byte injection, terminal-escape smuggling, homoglyph control tricks) is refused
cleanly with a 422 rather than being processed or logged raw. Ordinary whitespace
(space, tab, newline, carriage return) is allowed.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator

_ALLOWED_WHITESPACE = {"\t", "\n", "\r"}


def has_control_chars(value: str) -> bool:
    return any(
        (ord(ch) < 0x20 and ch not in _ALLOWED_WHITESPACE) or ord(ch) == 0x7F
        for ch in value
    )


def ensure_no_control_chars(value: str) -> str:
    if "\x00" in value:
        raise ValueError("value must not contain null bytes")
    if has_control_chars(value):
        raise ValueError("value must not contain control characters")
    return value


# A drop-in annotated string type for request fields that must be control-char free.
SafeStr = Annotated[str, AfterValidator(ensure_no_control_chars)]
