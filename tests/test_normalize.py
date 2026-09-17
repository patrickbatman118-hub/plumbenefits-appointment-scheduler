from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.normalize import DateTimeRejected, normalize_datetime

KOLKATA = ZoneInfo("Asia/Kolkata")


def test_next_friday_resolves_to_a_future_friday():
    now = datetime(2025, 1, 6, 10, 0, tzinfo=KOLKATA)  # a Monday
    date_str, time_str = normalize_datetime("next Friday", "3pm", now=now)
    resolved_date = datetime.fromisoformat(date_str).date()
    assert resolved_date.weekday() == 4  # Friday
    assert resolved_date > now.date()
    assert time_str == "15:00"


def test_tomorrow_morning_resolves_to_the_next_calendar_day():
    now = datetime(2025, 1, 6, 10, 0, tzinfo=KOLKATA)
    date_str, time_str = normalize_datetime("tomorrow", "9am", now=now)
    assert date_str == "2025-01-07"
    assert time_str == "09:00"


def test_unparsable_phrase_is_rejected():
    now = datetime(2025, 1, 6, 10, 0, tzinfo=KOLKATA)
    with pytest.raises(DateTimeRejected):
        normalize_datetime("whenever works", "sometime soonish", now=now)


def test_empty_phrases_are_rejected():
    now = datetime(2025, 1, 6, 10, 0, tzinfo=KOLKATA)
    with pytest.raises(DateTimeRejected):
        normalize_datetime("", "", now=now)


def test_missing_time_phrase_does_not_silently_default_to_midnight():
    # dateparser's own behavior for a date with no time is to assume 00:00 -
    # that's a real appointment slot, not a "failed to parse" signal, so it
    # must be rejected explicitly rather than booked as a midnight visit.
    now = datetime(2025, 1, 6, 10, 0, tzinfo=KOLKATA)
    with pytest.raises(DateTimeRejected):
        normalize_datetime("next Friday", "", now=now)
    with pytest.raises(DateTimeRejected):
        normalize_datetime("next Friday", "   ", now=now)


def test_placeholder_words_from_gemini_are_treated_as_blank():
    # Observed live: asked to return "" for a missing time_phrase, Gemini
    # instead returned the literal string "null". Must not be trusted to
    # coincidentally fail dateparser parsing.
    now = datetime(2025, 1, 6, 10, 0, tzinfo=KOLKATA)
    with pytest.raises(DateTimeRejected):
        normalize_datetime("next Friday", "null", now=now)
    with pytest.raises(DateTimeRejected):
        normalize_datetime("none", "3pm", now=now)
    with pytest.raises(DateTimeRejected):
        normalize_datetime("next Friday", "N/A", now=now)


def test_missing_date_phrase_is_rejected():
    now = datetime(2025, 1, 6, 10, 0, tzinfo=KOLKATA)
    with pytest.raises(DateTimeRejected):
        normalize_datetime("", "3pm", now=now)


def test_fully_specified_past_date_is_rejected():
    # PREFER_DATES_FROM="future" only disambiguates incomplete/relative
    # phrases - an unambiguous past date parses successfully as-is, so it
    # must be caught with an explicit "is this before now" check.
    now = datetime(2026, 9, 17, 14, 0, tzinfo=KOLKATA)
    with pytest.raises(DateTimeRejected, match="already passed"):
        normalize_datetime("2020-01-01", "3pm", now=now)


def test_same_day_time_already_passed_is_rejected():
    now = datetime(2026, 9, 17, 14, 0, tzinfo=KOLKATA)  # Thursday, 2pm
    with pytest.raises(DateTimeRejected, match="already passed"):
        normalize_datetime("today", "9am", now=now)


def test_same_day_time_still_ahead_is_accepted():
    now = datetime(2026, 9, 17, 14, 0, tzinfo=KOLKATA)  # Thursday, 2pm
    date_str, time_str = normalize_datetime("today", "5pm", now=now)
    assert date_str == "2026-09-17"
    assert time_str == "17:00"


def test_middle_of_the_night_is_rejected_as_outside_business_hours():
    # The most basic real-world constraint of all: nobody is taking a 2am
    # dentist appointment. Business hours are enforced independently of
    # whether the date/time phrase itself parses cleanly.
    now = datetime(2026, 9, 17, 10, 0, tzinfo=KOLKATA)  # Thursday
    with pytest.raises(DateTimeRejected, match="business hours"):
        normalize_datetime("tomorrow", "2am", now=now)


def test_appointment_must_fit_before_closing_time():
    # Clinic closes at 18:00 and appointments are 30 minutes - 17:45 would
    # run until 18:15, past closing, so it must be rejected even though
    # 17:45 itself is "during business hours."
    now = datetime(2026, 9, 17, 10, 0, tzinfo=KOLKATA)  # Thursday
    with pytest.raises(DateTimeRejected, match="business hours"):
        normalize_datetime("today", "5:45pm", now=now)


def test_last_bookable_slot_of_the_day_is_accepted():
    now = datetime(2026, 9, 17, 10, 0, tzinfo=KOLKATA)  # Thursday
    date_str, time_str = normalize_datetime("today", "5:30pm", now=now)
    assert date_str == "2026-09-17"
    assert time_str == "17:30"


def test_sunday_is_rejected_as_closed():
    now = datetime(2026, 9, 17, 10, 0, tzinfo=KOLKATA)  # Thursday
    with pytest.raises(DateTimeRejected, match="closed"):
        normalize_datetime("this Sunday", "11am", now=now)
