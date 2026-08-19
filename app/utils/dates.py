from datetime import date, datetime


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    # ISO-like year/month/day
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(value)
        return dt.date()
    except ValueError:
        pass
    # Common text formats (e.g., "Mar 31, 2017", "March 31, 2017", "31 Mar 2017")
    strptime_formats = [
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %Y",
        "%B %Y",
    ]
    for fmt in strptime_formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    if is_year_only(value):
        return date(int(value), 1, 1)
    if len(value) == 7 and value[4] == "-":
        year, month = value.split("-")
        if year.isdigit() and month.isdigit() and 1 <= int(month) <= 12:
            return date(int(year), int(month), 1)
    return None


def is_year_only(value: str | None) -> bool:
    return bool(value) and len(value) == 4 and value.isdigit()


def date_from_year(year: int, today: date, fallback: date | None = None) -> date:
    """Turn a year-only publication date into something the window filter can use.

    Dating every "2026" book 1 January would drop it as older than the window for
    most of the year, so a recent year is dated by ``fallback`` (e.g. a feed's
    updated_at) or by first sighting:
    - this year, or next year (Russian publishers print next year on books
      released in November-December): ``fallback`` or today;
    - last year during January-March, when such books are still new: today.
    Any other year keeps 1 January and is filtered as usual.
    """
    if year in (today.year, today.year + 1):
        return fallback or today
    if year == today.year - 1 and today.month <= 3:
        return today
    return date(year, 1, 1)


def parse_published_date(value: str | None, today: date) -> date | None:
    """parse_date, except year-only values go through date_from_year."""
    if is_year_only(value):
        return date_from_year(int(value), today)
    return parse_date(value)
