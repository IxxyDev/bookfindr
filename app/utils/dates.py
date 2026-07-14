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
    if len(value) == 4 and value.isdigit():
        return date(int(value), 1, 1)
    if len(value) == 7 and value[4] == "-":
        year, month = value.split("-")
        if year.isdigit() and month.isdigit():
            return date(int(year), int(month), 1)
    return None
