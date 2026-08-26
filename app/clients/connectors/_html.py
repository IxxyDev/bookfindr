from selectolax.lexbor import LexborHTMLParser


def strip_html(text: str | None) -> str:
    return LexborHTMLParser(text).text() if text else ""
