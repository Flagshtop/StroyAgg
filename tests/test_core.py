from datetime import date

from aggregator.delivery import parse_delivery, parse_price
from aggregator.models import Offer, mark_best

T = date(2026, 10, 27)


def d(s):
    return parse_delivery(s, T)[0]


def test_delivery():
    assert d("Доставка сегодня") == 0
    assert d("Курьером завтра") == 1
    assert d("послезавтра") == 2
    assert d("Доставка 30 октября") == 3
    assert d("пт, 31 окт") == 4
    assert d("2–4 дня") == 2
    assert d("от 1 до 3 дней") == 1
    assert d("Доставим за 5 рабочих дней") == 5
    assert d("Самовывоз сегодня; курьер 29 октября") == 0
    assert d("через 2 часа") == 0
    assert d("5 января") == (date(2027, 1, 5) - T).days
    assert d("Доставка 02.11") == 6
    assert d("1-2 недели") == 7
    assert d("") is None and d("В наличии") is None


def test_price():
    assert parse_price("1 299 ₽") == 1299
    assert parse_price("12 345,50 руб.") == 12345.5
    assert parse_price("—") is None


def test_mark_best():
    a = Offer("q", "A", "t", 100, "u1", delivery_days=5)
    b = Offer("q", "B", "t", 90, "u2", delivery_days=1)
    c = Offer("q2", "B", "t", None, "u3")
    mark_best([a, b, c])
    assert b.is_best_price and b.is_fastest and not a.is_best_price and not c.is_best_price
