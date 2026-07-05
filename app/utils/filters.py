COMPUTER_KEYWORDS = [
    "computer",
    "computers",
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
    "ai",
    "database",
    "програм",
    "информат",
    "вычисл",
    "сет",
    "данн",
    "ИБ",
    "кибер",
    "машин",
    "администр",
    "искусствен",
    "it",
]


def is_computing(text_fields: list[str]) -> bool:
    blob = " ".join(text_fields).lower()
    return any(keyword in blob for keyword in COMPUTER_KEYWORDS)
