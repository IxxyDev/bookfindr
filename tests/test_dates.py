from datetime import date

from app.utils.dates import date_from_year, is_year_only, parse_date, parse_published_date


def test_parse_iso_date():
    assert parse_date("2024-01-15") == date(2024, 1, 15)


def test_parse_iso_datetime():
    assert parse_date("2024-01-15T10:30:00") == date(2024, 1, 15)


def test_parse_datetime_with_offset_or_z():
    assert parse_date("2024-01-15T23:30:00+03:00") == date(2024, 1, 15)
    assert parse_date("2024-01-15T10:30:00Z") == date(2024, 1, 15)


def test_parse_year_only():
    assert parse_date("2024") == date(2024, 1, 1)


def test_parse_year_month():
    assert parse_date("2024-03") == date(2024, 3, 1)


def test_parse_text_format_short_month():
    assert parse_date("Mar 31, 2017") == date(2017, 3, 31)


def test_parse_text_format_full_month():
    assert parse_date("March 31, 2017") == date(2017, 3, 31)


def test_parse_text_format_day_first():
    assert parse_date("31 Mar 2017") == date(2017, 3, 31)


def test_parse_text_format_month_year():
    assert parse_date("Mar 2017") == date(2017, 3, 1)


def test_parse_none_returns_none():
    assert parse_date(None) is None


def test_parse_empty_string_returns_none():
    assert parse_date("") is None


def test_parse_garbage_returns_none():
    assert parse_date("not-a-date") is None
    assert parse_date("xyz123") is None


def test_parse_invalid_month_returns_none():
    assert parse_date("2024-13") is None
    assert parse_date("2024-00") is None


SEPTEMBER = date(2026, 9, 20)
FEBRUARY = date(2026, 2, 10)


def test_date_from_year_current_year_uses_fallback_or_today():
    assert date_from_year(2026, SEPTEMBER) == SEPTEMBER
    assert date_from_year(2026, SEPTEMBER, fallback=date(2026, 8, 1)) == date(2026, 8, 1)


def test_date_from_year_next_year_counts_as_current():
    # Russian publishers print next year on books released in November-December
    assert date_from_year(2027, SEPTEMBER) == SEPTEMBER
    assert date_from_year(2027, SEPTEMBER, fallback=date(2026, 8, 1)) == date(2026, 8, 1)


def test_date_from_year_last_year_is_recent_in_the_first_quarter():
    assert date_from_year(2025, FEBRUARY) == FEBRUARY
    assert date_from_year(2025, FEBRUARY, fallback=date(2025, 6, 1)) == FEBRUARY
    assert date_from_year(2025, SEPTEMBER) == date(2025, 1, 1)


def test_date_from_year_older_and_far_future_years_are_1_january():
    assert date_from_year(2020, SEPTEMBER, fallback=date(2026, 8, 1)) == date(2020, 1, 1)
    assert date_from_year(2028, SEPTEMBER) == date(2028, 1, 1)


def test_parse_published_date_routes_year_only_values_through_date_from_year():
    assert parse_published_date("2026", SEPTEMBER) == SEPTEMBER
    assert parse_published_date("2020", SEPTEMBER) == date(2020, 1, 1)
    assert parse_published_date("2026-03-05", SEPTEMBER) == date(2026, 3, 5)
    assert parse_published_date(None, SEPTEMBER) is None


def test_is_year_only():
    assert is_year_only("2026") is True
    assert is_year_only("2026-03") is False
    assert is_year_only(None) is False
