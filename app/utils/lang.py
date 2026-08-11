import re

# ISO 639-2 (bibliographic and terminology forms) to ISO 639-1. Open Library and
# MARC records use the three-letter codes, Google Books and connectors two letters.
ISO_639_2_TO_1 = {
    "ara": "ar",
    "bel": "be",
    "chi": "zh",
    "zho": "zh",
    "cze": "cs",
    "ces": "cs",
    "dut": "nl",
    "nld": "nl",
    "eng": "en",
    "fre": "fr",
    "fra": "fr",
    "ger": "de",
    "deu": "de",
    "heb": "he",
    "hin": "hi",
    "ita": "it",
    "jpn": "ja",
    "kaz": "kk",
    "kor": "ko",
    "pol": "pl",
    "por": "pt",
    "rus": "ru",
    "spa": "es",
    "swe": "sv",
    "tur": "tr",
    "ukr": "uk",
}

REGION_SUFFIX_RE = re.compile(r"[-_].*$")


def normalize_language(code: str | None) -> str | None:
    """Two-letter language code for ``code``; unknown codes come back lowercased."""
    if not code or not code.strip():
        return None
    base = REGION_SUFFIX_RE.sub("", code.strip().lower())
    return ISO_639_2_TO_1.get(base, base)
