from datetime import UTC, datetime
from decimal import Decimal

import pytest

from prices.normalize import (
    Pack,
    PriceParseError,
    RawOffer,
    detect_sale_mode,
    extract_brand,
    normalize_offer,
    parse_pack,
    parse_price,
    parse_price_per_kg,
)

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


# --- цена ---


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("129 99 ₽", "129.99"),  # Дикси: рубли и копейки раздельно
        ("129,99 ₽", "129.99"),
        ("129.99", "129.99"),
        ("129.9", "129.90"),
        ("1 299 ₽", "1299.00"),  # тысячи через пробел
        ("1 299,90 ₽", "1299.90"),  # неразрывный пробел
        ("1 299 90 ₽", "1299.90"),  # узкий неразрывный пробел + копейки
        ("12 345 678", "12345678.00"),
        ("от 89 руб.", "89.00"),
        ("89 рублей", "89.00"),
        ("89 р.", "89.00"),
        ("99", "99.00"),
        ("  45,5  ₽ ", "45.50"),
    ],
)
def test_parse_price(text, want):
    assert parse_price(text) == Decimal(want)


@pytest.mark.parametrize(
    "text", ["", "   ", "₽", "цена", "12.345.67", "1 2", "0", "0,00", "-5", None]
)
def test_parse_price_rejects_garbage(text):
    with pytest.raises(PriceParseError):
        parse_price(text)


# --- фасовка ---


@pytest.mark.parametrize(
    ("title", "want"),
    [
        ("Молоко Простоквашино 3,2%, 930 мл", Pack(930, "ml")),
        ("Вода питьевая 1,5 л", Pack(1500, "ml")),
        ("Сок 0.2л 3%", Pack(200, "ml")),
        ("Мука пшеничная 2 кг", Pack(2000, "g")),
        ("Масло сливочное 82,5% 180г", Pack(180, "g")),
        ("Сыр Российский 50%, 200 гр.", Pack(200, "g")),
        ("Йогурт 4 x 125 г", Pack(500, "g", count=4)),
        ("Йогурт 4х125 г", Pack(500, "g", count=4)),  # русская «х»
        ("Лук репчатый ~1 кг", Pack(1000, "g", approx=True)),
        ("Яйцо куриное С1, 10 шт", Pack(10, "pcs", count=10)),
        ("Лимон, 1 шт.", Pack(1, "pcs", count=1)),
        ("Набор 2 x 3 шт", Pack(6, "pcs", count=6)),
        # последнее упоминание: размер в конце названия
        ("Напиток 1 л, упаковка 0,5 л", Pack(500, "ml")),
    ],
)
def test_parse_pack(title, want):
    assert parse_pack(title) == want


@pytest.mark.parametrize(
    "title", ["Лимон", "", None, "Молоко 3,2%", "Кастрюля 2 литровая", "0 г", "0 x 100 г"]
)
def test_parse_pack_none(title):
    assert parse_pack(title) is None


# --- цена за кг ---


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("199,90 ₽/кг", "199.90"),
        ("Цена за 1 кг: 199,90 ₽", "199.90"),
        ("за кг 199 90", "199.90"),
        ("за 100 г 19,99 ₽", "199.90"),
        ("19,99 ₽/100 г", "199.90"),
        ("49,90 руб./л", "49.90"),
        ("за 100 мл 5 ₽", "50.00"),
    ],
)
def test_parse_price_per_kg(text, want):
    assert parse_price_per_kg(text) == Decimal(want)


@pytest.mark.parametrize("text", ["", None, "89 ₽ за 1 шт", "199,90 ₽"])
def test_parse_price_per_kg_without_unit(text):
    assert parse_price_per_kg(text) is None


def test_parse_price_per_kg_unreadable_price():
    with pytest.raises(PriceParseError):
        parse_price_per_kg("за 1 кг: дорого")


# --- способ продажи ---


@pytest.mark.parametrize(
    ("title", "pack", "price_unit", "want"),
    [
        ("Молоко 930 мл", Pack(930, "ml"), "pack", "pack_mass"),
        ("Яйцо С1 10 шт", Pack(10, "pcs", count=10), "pack", "pack_count"),
        ("Лимон 1 шт", Pack(1, "pcs", count=1), "pack", "per_piece"),
        ("Огурцы", None, "piece", "per_piece"),
        ("Огурцы", None, "kg", "by_weight"),
        ("Огурцы среднеплодные весовые", None, "pack", "by_weight"),
        ("Яблоки на вес", Pack(1000, "g", approx=True), "pack", "by_weight"),
        ("Конфеты развесные", None, "pack", "by_weight"),
        ("Что-то без фасовки", None, "pack", "unknown"),
    ],
)
def test_detect_sale_mode(title, pack, price_unit, want):
    assert detect_sale_mode(title, pack, price_unit) == want


# --- марка ---


@pytest.mark.parametrize(
    ("title", "known", "want"),
    [
        ("Молоко «Простоквашино» 3,2%, 930 мл", (), "Простоквашино"),
        ('Масло "Экомилк" сливочное 82,5%', (), "Экомилк"),
        ("Молоко Домик в деревне 3,2%", ("Домик", "Домик в деревне"), "Домик в деревне"),
        ("Творог ПРОСТОКВАШИНО 5%", ("Простоквашино",), "Простоквашино"),
        ("Сыр Белебеевский", ("Бел",), ""),  # часть слова — не марка
        ("Лук репчатый", ("Простоквашино",), ""),
        ("", (), ""),
    ],
)
def test_extract_brand(title, known, want):
    assert extract_brand(title, known) == want


# --- карточка целиком ---


def offer(**kw):
    base = dict(
        store="dixy", external_id="123", title="Молоко «Простоквашино» 3,2%, 930 мл",
        price_text="89 99 ₽", fetched_at=NOW,
    )  # fmt: skip
    base.update(kw)
    return RawOffer(**base)


def test_normalize_pack_mass_with_derived_price_per_kg():
    n = normalize_offer(offer(card_price_text="79,99 ₽"))
    assert (n.brand, n.sale_mode, n.pack_qty, n.pack_unit) == (
        "Простоквашино",
        "pack_mass",
        930,
        "ml",
    )
    assert (n.price, n.card_price) == (Decimal("89.99"), Decimal("79.99"))
    assert n.price_per_kg == Decimal("96.76")  # 89.99 / 930 * 1000
    assert n.notes == ("price_per_kg_derived",) and n.source == "site"
    assert (n.in_stock, n.store_only, n.fetched_at) == (True, False, NOW)


def test_normalize_uses_explicit_unit_price_and_brand_hint():
    n = normalize_offer(offer(unit_price_text="96,50 ₽/л", brand_hint=" Свой бренд "))
    assert n.price_per_kg == Decimal("96.50") and n.notes == () and n.brand == "Свой бренд"


def test_normalize_by_weight():
    n = normalize_offer(
        offer(title="Лук репчатый ~1 кг", price_text="39 99", price_unit="kg", store="lenta")
    )
    assert (n.sale_mode, n.pack_qty, n.pack_unit) == ("by_weight", None, None)
    assert n.price_per_kg == Decimal("39.99") and n.brand == ""


def test_normalize_pack_count_and_per_piece():
    eggs = normalize_offer(offer(title="Яйцо куриное С1, 10 шт", price_text="119,90"))
    assert (eggs.sale_mode, eggs.pack_qty, eggs.pack_unit, eggs.price_per_kg) == (
        "pack_count", 10, "pcs", None,
    )  # fmt: skip
    lemon = normalize_offer(offer(title="Лимон", price_text="25", price_unit="piece"))
    assert (lemon.sale_mode, lemon.pack_qty, lemon.pack_unit) == ("per_piece", None, None)


def test_normalize_unknown_mode_and_bad_card_price_are_noted():
    n = normalize_offer(offer(title="Набор для пикника", card_price_text="по карте"))
    assert n.sale_mode == "unknown" and n.card_price is None and n.price_per_kg is None
    assert n.notes == ("card_price_unreadable", "sale_mode_unknown")


def test_normalize_flags_and_whitespace():
    n = normalize_offer(
        offer(title="  Молоко 930 мл ", in_stock=False, store_only=True, category="Молочное")
    )
    assert (n.title, n.in_stock, n.store_only, n.category) == (
        "Молоко 930 мл",
        False,
        True,
        "Молочное",
    )


def test_normalize_unreadable_price_raises():
    with pytest.raises(PriceParseError):
        normalize_offer(offer(price_text="нет в наличии"))
