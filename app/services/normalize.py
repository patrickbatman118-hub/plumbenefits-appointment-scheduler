"""Deterministic date/time normalization.

This is the core "we don't let the LLM do date math" decision (README
"Design Decisions" #1): given the phrases Gemini extracted, resolve them to
an ISO date/time using `dateparser`, anchored to a real "now" in the
configured timezone. Pure function, no network calls, fully unit-testable -
see tests/test_normalize.py.
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import dateparser

from app.config import get_settings

settings = get_settings()

# dateparser (as of 1.4.3) fails to parse "next <weekday>" / "this <weekday>"
# as a single phrase - "Friday" alone parses fine, "next week" alone parses
# fine, but "next Friday" returns None. Confirmed by hand while building this.
# Workaround: if the full phrase fails, retry with the leading modifier
# stripped and let PREFER_DATES_FROM="future" pick the correct upcoming
# occurrence of that weekday instead.
_LEADING_MODIFIER = re.compile(r"^\s*(next|this|coming)\s+", re.IGNORECASE)


def _try_parse(phrase: str, reference: datetime) -> datetime | None:
    return dateparser.parse(
        phrase,
        settings={
            "TIMEZONE": settings.app_timezone,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "RELATIVE_BASE": reference,
            "PREFER_DATES_FROM": "future",
        },
    )


def normalize_datetime(
    date_phrase: str, time_phrase: str, now: datetime | None = None
) -> tuple[str, str] | None:
    tz = ZoneInfo(settings.app_timezone)
    reference = now or datetime.now(tz)

    combined = f"{date_phrase} {time_phrase}".strip()
    parsed = _try_parse(combined, reference)

    if parsed is None:
        stripped_date_phrase = _LEADING_MODIFIER.sub("", date_phrase)
        fallback = f"{stripped_date_phrase} {time_phrase}".strip()
        if fallback != combined:
            parsed = _try_parse(fallback, reference)

    if parsed is None:
        return None
    return parsed.date().isoformat(), parsed.strftime("%H:%M")
