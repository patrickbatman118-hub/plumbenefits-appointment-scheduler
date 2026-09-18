"""Deterministic date/time normalization.

This is the core "we don't let the LLM do date math" decision (README
"Design Decisions" #1): given the phrases Gemini extracted, resolve them to
an ISO date/time using `dateparser`, anchored to a real "now" in the
configured timezone. Pure function, no network calls, fully unit-testable -
see tests/test_normalize.py.
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import dateparser

from app.config import get_settings
from app.constants import (
    APPOINTMENT_DURATION_MINUTES,
    BUSINESS_END_HOUR,
    BUSINESS_START_HOUR,
    CLOSED_WEEKDAYS,
    MAX_BOOKING_HORIZON_DAYS,
    MIN_BOOKING_NOTICE_MINUTES,
)

settings = get_settings()

# dateparser (as of 1.4.3) fails to parse "next <weekday>" / "this <weekday>"
# as a single phrase - "Friday" alone parses fine, "next week" alone parses
# fine, but "next Friday" returns None. Confirmed by hand while building this.
# Workaround: if the full phrase fails, retry with the leading modifier
# stripped and let PREFER_DATES_FROM="future" pick the correct upcoming
# occurrence of that weekday instead.
_LEADING_MODIFIER = re.compile(r"^\s*(next|this|coming)\s+", re.IGNORECASE)

# Gemini is prompted to return "" when a request has no date/time phrase, but
# a prompt is a request, not a guarantee - observed it return the literal
# string "null" for a missing time_phrase while testing this. Treated the
# same as an empty string rather than trusted to fail parsing by luck.
_BLANK_PHRASE_SENTINELS = {"", "null", "none", "n/a", "na", "unknown", "nil"}


class DateTimeRejected(Exception):
    """Raised with a human-readable reason whenever a date/time can't be
    accepted for booking - unparsable, in the past, or outside business
    hours. The router surfaces str(exc) directly as the guardrail message."""


def _is_blank_phrase(phrase: str) -> bool:
    return phrase.strip().lower() in _BLANK_PHRASE_SENTINELS


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


def normalize_datetime(date_phrase: str, time_phrase: str, now: datetime | None = None) -> tuple[str, str]:
    """Returns (date, time) as ISO strings, or raises DateTimeRejected."""
    tz = ZoneInfo(settings.app_timezone)
    reference = now or datetime.now(tz)

    # dateparser fills gaps instead of failing: a date with no time defaults
    # to midnight rather than erroring. Reject blank phrases explicitly
    # instead of letting a partial input produce a made-up result.
    if _is_blank_phrase(date_phrase) or _is_blank_phrase(time_phrase):
        raise DateTimeRejected("No date or time was mentioned in the request")

    combined = f"{date_phrase} {time_phrase}".strip()
    parsed = _try_parse(combined, reference)

    if parsed is None:
        stripped_date_phrase = _LEADING_MODIFIER.sub("", date_phrase)
        fallback = f"{stripped_date_phrase} {time_phrase}".strip()
        if fallback != combined:
            parsed = _try_parse(fallback, reference)

    if parsed is None:
        raise DateTimeRejected(f"Could not understand the date/time phrase \"{combined}\"")

    # PREFER_DATES_FROM="future" only disambiguates relative phrases (e.g. a
    # bare weekday) - a fully-specified past date/time parses as-is and must
    # be rejected explicitly.
    if parsed <= reference:
        raise DateTimeRejected("That date/time has already passed")

    # Every scheduling tool researched enforces some minimum lead time
    # (Calendly "minimum scheduling notice", Cal.com "minimum notice",
    # Google Calendar's own 1-hour floor) - nobody can book something
    # starting in the next few minutes. See app/constants.py for citations.
    if parsed < reference + timedelta(minutes=MIN_BOOKING_NOTICE_MINUTES):
        raise DateTimeRejected(f"Appointments need at least {MIN_BOOKING_NOTICE_MINUTES} minutes' notice")

    # Equally universal in the other direction (Google Calendar defaults to
    # a 60-day booking window) - guards against, e.g., a misread year from
    # noisy OCR resolving to some date years out.
    if parsed > reference + timedelta(days=MAX_BOOKING_HORIZON_DAYS):
        raise DateTimeRejected(f"Cannot book more than {MAX_BOOKING_HORIZON_DAYS} days in advance")

    # No clinic is open 24/7. Applied identically to every department - see
    # app/constants.py for why this is a global assumption, not per-department
    # config, and the README's "Known scope simplifications".
    if parsed.weekday() in CLOSED_WEEKDAYS:
        raise DateTimeRejected(f"We're closed on {parsed.strftime('%A')}s")

    business_start = parsed.replace(hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0)
    business_end = parsed.replace(hour=BUSINESS_END_HOUR, minute=0, second=0, microsecond=0)
    appointment_end = parsed + timedelta(minutes=APPOINTMENT_DURATION_MINUTES)
    if parsed < business_start or appointment_end > business_end:
        raise DateTimeRejected(
            f"Requested time is outside business hours "
            f"({BUSINESS_START_HOUR:02d}:00-{BUSINESS_END_HOUR:02d}:00)"
        )

    return parsed.date().isoformat(), parsed.strftime("%H:%M")
