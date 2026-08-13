import re

SEPARATORS_RE = re.compile(r"[-\s]")
ISBN13_RE = re.compile(r"97[89]\d{10}")
ISBN10_RE = re.compile(r"\d{9}[\dX]")


def _compact(value: str | None) -> str:
    return SEPARATORS_RE.sub("", value or "").upper()


def normalize_isbn13(value: str | None) -> str | None:
    """Digits-only ISBN-13, or None when ``value`` is not exactly one ISBN-13."""
    compact = _compact(value)
    return compact if ISBN13_RE.fullmatch(compact) else None


def normalize_isbn10(value: str | None) -> str | None:
    """Compact ISBN-10 (check digit may be X), or None when ``value`` is not one."""
    compact = _compact(value)
    return compact if ISBN10_RE.fullmatch(compact) else None
