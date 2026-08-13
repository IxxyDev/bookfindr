import re

# Matched at the start of a word, case-insensitively: "program" covers programming,
# programmer; a substring match let "сет" hit "посетитель" and "данн" hit "данный".
COMPUTING_STEMS = [
    "computer",
    "program",
    "informatics",
    "information technology",
    "linux",
    "windows",
    "network",
    "security",
    "cyber",
    "data",
    "machine learning",
    "cloud",
    "devops",
    "програм",
    "информат",
    "вычисл",
    "сет",
    r"данн(?:ые|ых|ым|ыми)\b",
    "кибер",
    "машинн",
    "администрирован",
    r"искусственн\w* интеллект",
]
# Matched as whole words, case-sensitively: lowercased, "it" is the English pronoun.
COMPUTING_ACRONYMS = ["IT", "AI", "ИБ"]

COMPUTING_STEMS_RE = re.compile(r"\b(?:" + "|".join(COMPUTING_STEMS) + ")", re.IGNORECASE)
COMPUTING_ACRONYMS_RE = re.compile(r"\b(?:" + "|".join(COMPUTING_ACRONYMS) + r")\b")


def is_computing(text_fields: list[str]) -> bool:
    blob = " ".join(text_fields)
    return bool(COMPUTING_STEMS_RE.search(blob) or COMPUTING_ACRONYMS_RE.search(blob))
