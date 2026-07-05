from datetime import date

from app.utils.dates import parse_date


def test_parse_iso_date():
    assert parse_date("2024-01-15") == date(2024, 1, 15)


def test_parse_iso_datetime():
    assert parse_date("2024-01-15T10:30:00") == date(2024, 1, 15)


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
