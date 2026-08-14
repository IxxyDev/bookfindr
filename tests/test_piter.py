from datetime import date, timedelta

from app.clients import connectors

YEAR_PROPERTY = 1
PRINT_YEAR_PROPERTY = 2


def _product(product_id: int, *, year: int | None = None, print_year: int | None = None) -> dict:
    characteristics = []
    if year is not None:
        characteristics.append({"property_id": YEAR_PROPERTY, "title": str(year)})
    if print_year is not None:
        characteristics.append({"property_id": PRINT_YEAR_PROPERTY, "title": str(print_year)})
    return {
        "id": product_id,
        "title": f"Книга {product_id}",
        "url": f"/product/{product_id}",
        "updated_at": (date.today() - timedelta(days=2)).isoformat() + "T10:00:00Z",
        "properties": [
            {"id": YEAR_PROPERTY, "title": "Год"},
            {"id": PRINT_YEAR_PROPERTY, "title": "Год тиража"},
        ],
        "characteristics": characteristics,
    }


def test_print_year_dates_a_product_without_a_publication_year():
    assert connectors._piter_published_date(_product(1, print_year=2015)) == date(2015, 1, 1)


def test_publication_year_wins_over_print_year():
    assert connectors._piter_published_date(_product(1, year=2014, print_year=2015)) == date(
        2014, 1, 1
    )
