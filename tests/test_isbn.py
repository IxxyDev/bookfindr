from app.utils.isbn import normalize_isbn10, normalize_isbn13


def test_isbn13_strips_hyphens_and_spaces():
    assert normalize_isbn13("978-5-4461-2345-6") == "9785446123456"
    assert normalize_isbn13(" 979 8 8688 0001 2 ") == "9798868800012"


def test_isbn13_rejects_wrong_length_or_prefix():
    assert normalize_isbn13("978544612345") is None  # 12 digits
    assert normalize_isbn13("97854461234567") is None  # 14 digits
    assert normalize_isbn13("1234567890123") is None  # not 978/979
    assert normalize_isbn13("5-4461-2345-6") is None  # an ISBN-10


def test_isbn13_rejects_lists_and_garbage():
    assert normalize_isbn13("978-5-4461-2345-6, 978-5-4461-2345-7") is None
    assert normalize_isbn13("ISBN 9785446123456") is None
    assert normalize_isbn13(None) is None
    assert normalize_isbn13("") is None


def test_isbn10_accepts_digits_and_check_x():
    assert normalize_isbn10("5-4461-2345-6") == "5446123456"
    assert normalize_isbn10("0-306-40615-x") == "030640615X"


def test_isbn10_rejects_everything_else():
    assert normalize_isbn10("9785446123456") is None
    assert normalize_isbn10("54461234") is None
    assert normalize_isbn10("X306406152") is None
    assert normalize_isbn10(None) is None
