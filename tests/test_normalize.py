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
