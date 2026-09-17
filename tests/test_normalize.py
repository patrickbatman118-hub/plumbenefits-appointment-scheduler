from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.normalize import normalize_datetime

KOLKATA = ZoneInfo("Asia/Kolkata")


def test_next_friday_resolves_to_a_future_friday():
    now = datetime(2025, 1, 6, 10, 0, tzinfo=KOLKATA)  # a Monday
    resolved = normalize_datetime("next Friday", "3pm", now=now)
    assert resolved is not None
    date_str, time_str = resolved
    resolved_date = datetime.fromisoformat(date_str).date()
    assert resolved_date.weekday() == 4  # Friday
    assert resolved_date > now.date()
    assert time_str == "15:00"


def test_tomorrow_morning_resolves_to_the_next_calendar_day():
    now = datetime(2025, 1, 6, 10, 0, tzinfo=KOLKATA)
    date_str, time_str = normalize_datetime("tomorrow", "9am", now=now)
    assert date_str == "2025-01-07"
    assert time_str == "09:00"


def test_unparsable_phrase_returns_none_to_trigger_guardrail():
    now = datetime(2025, 1, 6, 10, 0, tzinfo=KOLKATA)
    assert normalize_datetime("whenever works", "sometime soonish", now=now) is None


def test_empty_phrases_return_none():
    now = datetime(2025, 1, 6, 10, 0, tzinfo=KOLKATA)
    assert normalize_datetime("", "", now=now) is None


def test_missing_time_phrase_does_not_silently_default_to_midnight():
    # dateparser's own behavior for a date with no time is to assume 00:00 -
    # that's a real appointment slot, not a "failed to parse" signal, so it
    # must be rejected explicitly rather than booked as a midnight visit.
    now = datetime(2025, 1, 6, 10, 0, tzinfo=KOLKATA)
    assert normalize_datetime("next Friday", "", now=now) is None
    assert normalize_datetime("next Friday", "   ", now=now) is None


def test_placeholder_words_from_gemini_are_treated_as_blank():
    # Observed live: asked to return "" for a missing time_phrase, Gemini
    # instead returned the literal string "null". Must not be trusted to
    # coincidentally fail dateparser parsing.
    now = datetime(2025, 1, 6, 10, 0, tzinfo=KOLKATA)
    assert normalize_datetime("next Friday", "null", now=now) is None
    assert normalize_datetime("none", "3pm", now=now) is None
    assert normalize_datetime("next Friday", "N/A", now=now) is None


def test_missing_date_phrase_returns_none():
    now = datetime(2025, 1, 6, 10, 0, tzinfo=KOLKATA)
    assert normalize_datetime("", "3pm", now=now) is None


def test_fully_specified_past_date_is_rejected():
    # PREFER_DATES_FROM="future" only disambiguates incomplete/relative
    # phrases - an unambiguous past date parses successfully as-is, so it
    # must be caught with an explicit "is this before now" check.
    now = datetime(2026, 9, 17, 14, 0, tzinfo=KOLKATA)
    assert normalize_datetime("2020-01-01", "3pm", now=now) is None


def test_same_day_time_already_passed_is_rejected():
    now = datetime(2026, 9, 17, 14, 0, tzinfo=KOLKATA)  # 2pm
    assert normalize_datetime("today", "9am", now=now) is None


def test_same_day_time_still_ahead_is_accepted():
    now = datetime(2026, 9, 17, 14, 0, tzinfo=KOLKATA)  # 2pm
    date_str, time_str = normalize_datetime("today", "6pm", now=now)
    assert date_str == "2026-09-17"
    assert time_str == "18:00"
