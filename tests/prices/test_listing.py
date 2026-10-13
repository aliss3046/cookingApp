import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from payloads import card, devalue, nuxt_page, page_with

from prices.listing import (
    STRATEGY_JSON_LD,
    STRATEGY_NEXT,
    STRATEGY_NUXT,
    Listing,
    extract_categories,
    extract_offers,
    hydrate_devalue,
)
from prices.normalize import normalize_offer

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def offers(page, **kw):
    return extract_offers(page, store="magnit", now=NOW, **kw)


# --- devalue ---


def test_hydrate_plain_structure_and_shared_references():
    shared = {"x": 1}
    root = {"a": shared, "b": [shared, "s", 2.5, True, None]}
    out = hydrate_devalue(devalue(root))
    assert out == root
    # одна и та же запись остаётся одним объектом (ссылка, а не копия)
    shared_raw = [{"a": 1, "b": 1}, {"x": 2}, 5]
    out2 = hydrate_devalue(shared_raw)
    assert out2["a"] is out2["b"]


def test_hydrate_nuxt_wrappers_and_opaque_values():
    raw = [
        {"r": 1, "e": 3, "d": 4, "none": -1},  # -1 как ссылка: «неопределено»
        ["Reactive", 2],
        {"k": 5},
        ["EmptyShallowRef", -1],
        ["Date", "2026-01-01"],
        "text",
    ]
    out = hydrate_devalue(raw)
    assert out["r"] == {"k": "text"}  # обёртка Reactive раскрыта
    assert out["e"] is None and out["none"] is None
    assert out["d"] == ["Date", "2026-01-01"]  # непрозрачные типы остаются как есть


def test_hydrate_out_of_range_is_none():
    assert hydrate_devalue([{"a": 99}]) == {"a": None}


# --- карточки Nuxt ---


def test_nuxt_cards_become_raw_offers():
    page = page_with(
        [
            card("1", "Молоко «Простоквашино» 3,2% 930 мл", "89.99"),
            card("2", "Лук репчатый", "37.09", unit="700г", unit_price=5299),
            card("3", "Бананы", 159.99, unit="1кг", unit_price=15999),
        ]
    )
    listing = offers(page, category="Овощи")
    assert isinstance(listing, Listing) and listing.strategy == STRATEGY_NUXT
    assert [o.external_id for o in listing.offers] == ["1", "2", "3"]
    milk, onion, banana = listing.offers
    assert (milk.price_text, milk.price_unit, milk.category) == ("89.99", "pack", "Овощи")
    # весовой: цена за кг из копеек, фасовка из unit прикреплена к названию
    assert (onion.title, onion.price_text, onion.price_unit) == ("Лук репчатый 700г", "52.99", "kg")
    assert banana.price_text == "159.99" and banana.title == "Бананы 1кг"
    assert milk.store == "magnit" and milk.fetched_at == NOW


def test_nuxt_weighted_offer_normalizes_to_price_per_kg():
    [onion] = offers(
        page_with([card("2", "Лук репчатый", "37.09", unit="700г", unit_price=5299)])
    ).offers
    n = normalize_offer(onion)
    assert (n.sale_mode, n.price_per_kg, n.price) == (
        "by_weight",
        Decimal("52.99"),
        Decimal("52.99"),
    )


def test_unit_already_in_title_is_not_repeated():
    [o] = offers(page_with([card("1", "Молоко 930мл", "89.99", unit="930мл")])).offers
    assert o.title == "Молоко 930мл"


def test_stock_flag_from_quantity():
    page = page_with(
        [
            card("1", "А", "10", quantity=0),
            card("2", "Б", "10", quantity=None),
            card("3", "В", "10", quantity=5),
            card("4", "Г", "10", quantity=True),
        ]
    )
    assert [o.in_stock for o in offers(page).offers] == [False, True, True, True]


def test_bad_cards_are_skipped_and_counted_and_duplicates_dropped():
    page = page_with(
        [
            card("1", "Хорошая", "10"),
            card("2", "Без цены", ""),
            card("3", "Нулевая цена", "0"),
            card("4", "   ", "10"),
            card("5", "Цена мусор", "скоро"),
            card("1", "Хорошая", "10"),  # дубль по id
            {"price": "5", "name": 7},  # название не строка
        ]
    )
    listing = offers(page)
    assert [o.external_id for o in listing.offers] == ["1"]
    assert listing.skipped == 5


def test_price_formats_in_cards():
    page = page_with([card("1", "А", "1 299,50"), card("2", "Б", 45), card("3", "В", "99,9")])
    assert [o.price_text for o in offers(page).offers] == ["1299.50", "45.00", "99.90"]


# --- другие форматы ---


def test_next_data_is_walked_as_plain_json():
    data = {"props": {"items": [{"name": "Кефир 900 г", "price": 79, "sku": "k1"}]}}
    page = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    listing = offers(page)
    assert listing.strategy == STRATEGY_NEXT and listing.offers[0].external_id == "k1"
    assert listing.offers[0].price_text == "79.00"


def test_json_ld_products_and_offer_lists():
    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Product",
                "name": "Сыр Российский 200 г",
                "sku": "s1",
                "offers": {"price": "199.90"},
            },
            {
                "@type": ["Product"],
                "name": "Масло 180 г",
                "url": "https://x.test/m",
                "offers": [{"price": 150}],
            },
            {"@type": "Product", "name": "Без предложения"},
            {"@type": "BreadcrumbList"},
        ],
    }
    page = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    listing = offers(page)
    assert listing.strategy == STRATEGY_JSON_LD
    assert [o.external_id for o in listing.offers] == ["s1", "https://x.test/m"]
    assert listing.skipped == 1


def test_broken_json_and_empty_page_give_empty_listing():
    assert offers("<html>просто текст</html>") == Listing((), None, 0)
    page = (
        '<script id="__NUXT_DATA__">{не json</script>'
        '<script id="__NEXT_DATA__">{тоже</script>'
        '<script type="application/ld+json">{плохо</script>'
    )
    assert offers(page) == Listing((), None, 0)


def test_strategies_fall_through_to_the_next_one():
    ld = {"@type": "Product", "name": "Яйца 10 шт", "sku": "e1", "offers": {"price": "120"}}
    page = (
        nuxt_page({"nothing": "here"})
        + f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    )
    listing = offers(page)
    assert listing.strategy == STRATEGY_JSON_LD and listing.offers[0].external_id == "e1"


def test_nuxt_data_that_is_not_a_list_is_walked_as_json():
    state = {"a": {"title": "Рис 900 г", "price": 90, "id": 7}}
    page = f'<script id="__NUXT_DATA__">{json.dumps(state)}</script>'
    assert offers(page).offers[0].external_id == "7"


# --- категории ---


def test_category_tree():
    tree = {
        "categories": [
            {
                "id": "1", "name": "Молочный прилавок", "code": "milk",
                "children": [
                    {"id": "2", "name": "Сыры", "code": "cheese", "children": [
                        {"id": "3", "name": "Твердые", "code": "hard", "children": []},
                    ]},
                    {"id": "4", "name": "Молоко", "code": "milk_p", "children": None},
                ],
            },
            {"id": "1", "name": "Дубль", "code": "milk", "children": []},
            {"name": "Без кода", "children": []},
        ]
    }  # fmt: skip
    assert extract_categories(nuxt_page(tree)) == [
        (0, "1", "milk", "Молочный прилавок"),
        (1, "2", "cheese", "Сыры"),
        (2, "3", "hard", "Твердые"),
        (1, "4", "milk_p", "Молоко"),
    ]


def test_categories_absent_or_broken():
    assert extract_categories("<html></html>") == []
    assert extract_categories('<script id="__NUXT_DATA__">{плохо</script>') == []
    plain = {"x": [{"code": "a", "name": "A", "children": []}]}
    page = f'<script id="__NUXT_DATA__">{json.dumps(plain)}</script>'
    assert extract_categories(page) == [(0, "", "a", "A")]


@pytest.mark.parametrize("bad", [True, False, None, [], {}, "abc"])
def test_non_numeric_price_values_are_rejected(bad):
    assert offers(page_with([card("1", "А", bad)])).offers == ()


def test_hydrate_list_that_starts_with_a_plain_string():
    assert hydrate_devalue([["abc", 1], 7]) == ["abc", 7]  # не обёртка и не служебный тип


def test_shared_nodes_are_visited_once():
    from prices.listing import _walk

    shared_dict = {"title": "Общий", "price": "10"}
    shared_list = [shared_dict]
    root = {"a": shared_list, "b": shared_list, "c": shared_dict}  # одни и те же объекты
    assert list(_walk(root)) == [root, shared_dict]  # каждый объект один раз, в порядке документа


def test_json_ld_duplicate_products_are_dropped():
    ld = [
        {"@type": "Product", "name": "Кефир 900 г", "sku": "k1", "offers": {"price": "70"}},
        {"@type": "Product", "name": "Кефир 900 г", "sku": "k1", "offers": {"price": "70"}},
    ]
    page = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    assert len(offers(page).offers) == 1


def test_html_cards_from_real_dixy_markup():
    from pathlib import Path

    page = (Path(__file__).parent / "fixtures" / "dixy_cards.html").read_text(encoding="utf-8")
    listing = extract_offers(page, store="dixy", now=NOW, category="ovoshchi")
    assert listing.strategy == "html" and listing.skipped == 1
    onion, yalta, sale = listing.offers
    assert (onion.external_id, onion.title) == ("10E0074356", "Лук репчатый")
    assert (onion.price_text, onion.price_unit) == ("41.89", "kg")  # весовой: цена за кг
    assert yalta.title == 'Лук "Ялтинский", в упаковке, 360 г' and yalta.price_unit == "pack"
    assert sale.price_text == "89.99"  # текущая цена, а не зачёркнутая 119.90
    assert all(o.store == "dixy" and o.category == "ovoshchi" for o in listing.offers)


def test_html_cards_without_unit_and_duplicates_and_blank_title():
    def art(pid, title, unit=""):
        action = f'<div data-bsk_data="1 1 1 {unit} 0">' if unit else "<div>"
        return (
            f'<article class="card" product-id="{pid}"><p class="card__title">{title}</p>'
            f'{action}<div class="card__price-num">10.<span>50</span></div></div></article>'
        )

    page = art("a", "Соль") + art("a", "Соль повтор", "кг") + art("b", "  ")
    listing = extract_offers(page, store="dixy", now=NOW)
    assert [o.external_id for o in listing.offers] == ["a"]
    assert listing.offers[0].price_unit == "pack" and listing.skipped == 1
