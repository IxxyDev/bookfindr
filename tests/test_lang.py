from app.utils.lang import normalize_language


def test_iso_639_2_codes_become_two_letter():
    assert normalize_language("eng") == "en"
    assert normalize_language("rus") == "ru"
    assert normalize_language("ger") == "de"
    assert normalize_language("deu") == "de"
    assert normalize_language("fre") == "fr"
    assert normalize_language("spa") == "es"


def test_two_letter_codes_pass_through_lowercased():
    assert normalize_language("en") == "en"
    assert normalize_language("RU") == "ru"


def test_region_suffix_is_dropped():
    assert normalize_language("pt-BR") == "pt"
    assert normalize_language("zh_CN") == "zh"


def test_unknown_code_is_kept_lowercased():
    assert normalize_language("XYZ") == "xyz"


def test_empty_values_are_none():
    assert normalize_language(None) is None
    assert normalize_language("") is None
    assert normalize_language("  ") is None
