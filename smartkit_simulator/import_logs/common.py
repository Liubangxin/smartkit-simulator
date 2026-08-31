"""Shared helpers for the execution-log parsers."""

import re

#: Log levels that never identify a protocol thread.
_LEVELS = {"INFO", "WARN", "ERROR", "DEBUG"}


def log_thread_id(text):
    """Best-effort thread identifier from bracketed log segments."""
    matches = re.findall(r"\[([^\]\r\n]+)\](?:\(pid-[^)]+\))?", text)
    return next((value for value in reversed(matches) if value not in _LEVELS), "")
