from app.utils.filters import is_computing


def test_non_computing_text_is_rejected():
    assert is_computing(["A cookbook with recipes"]) is False
    assert is_computing(["Cooking: it is easy, said the editor"]) is False
    assert is_computing(["Данный роман о посетителях музея"]) is False
    assert is_computing(["Сказки народов мира"]) is False


def test_english_stems_match_at_word_start():
    assert is_computing(["Programming Rust"]) is True
    assert is_computing(["Computers / Networking"]) is True
    assert is_computing(["Designing Data-Intensive Applications"]) is True
    assert is_computing(["Machine Learning Engineering"]) is True


def test_russian_stems_match_at_word_start():
    assert is_computing(["Программирование на Python"]) is True
    assert is_computing(["Компьютерные сети"]) is True
    assert is_computing(["Анализ данных"]) is True
    assert is_computing(["Кибербезопасность для всех"]) is True


def test_acronyms_match_as_whole_upper_case_words():
    assert is_computing(["IT-инфраструктура предприятия"]) is True
    assert is_computing(["Generative AI in practice"]) is True
    assert is_computing(["Основы ИБ"]) is True
    assert is_computing(["Editorial"]) is False  # "it" inside a word
    assert is_computing(["Детские сказки и игры"]) is False  # "иб" not standalone


def test_empty_input_is_rejected():
    assert is_computing([]) is False
    assert is_computing([""]) is False
