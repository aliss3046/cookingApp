import pytest

from importers.directory import Directory, Ingredient
from importers.draft import (
    REASON_AMBIGUOUS,
    REASON_NO_MATCH,
    REASON_UNIT_UNKNOWN,
    WARNING_NO_INGREDIENTS,
    WARNING_SERVINGS_UNKNOWN,
    build_draft,
    parse_servings,
)
from importers.ingredient_line import REASON_NO_QUANTITY


@pytest.fixture
def d():
    return Directory(
        [
            Ingredient("garlic", "чеснок", piece_weight_g=50, unit_weights_g={"clove": 5}),
            Ingredient("dill", "укроп", piece_weight_g=30),
            Ingredient("flour", "мука"),
            Ingredient("milk", "молоко"),
            Ingredient("salt", "соль"),
            Ingredient("pepper", "перец"),
            Ingredient("butter", "масло сливочное"),
            Ingredient("oil", "масло растительное"),
            Ingredient("corn", "кукуруза", piece_weight_g=340),
        ]
    )


@pytest.mark.parametrize(
    ("value", "want"),
    [
        (4, 4),
        (4.0, 4),
        ("4 порции", 4),
        ("на 6 персон", 6),
        (["4", "4 servings"], 4),
        (["много", "2"], 2),
        ("много", None),
        ([], None),
        (None, None),
        (True, None),
        (0, None),
        (500, None),
        ({"value": 4}, None),
    ],
)
def test_parse_servings(value, want):
    assert parse_servings(value) == want


def test_quantities_are_per_serving(d):
    draft = build_draft("Блины", ["Мука — 200 г", "Молоко — 500 мл"], d, servings="4 порции")
    flour, milk = draft.lines
    assert (flour.ingredient_id, flour.qty_per_serving, flour.unit) == ("flour", 50, "g")
    assert (milk.ingredient_id, milk.qty_per_serving, milk.unit) == ("milk", 125, "ml")
    assert draft.default_servings == 4 and draft.warnings == () and draft.review_count == 0


def test_clove_converted_to_grams_head_stays_piece(d):
    draft = build_draft("Соус", ["3 зубчика чеснока", "1 головка чеснока"], d, servings=1)
    cloves, head = draft.lines
    assert (cloves.qty_per_serving, cloves.unit) == (15, "g")
    assert (head.qty_per_serving, head.unit) == (1, "pcs")


def test_measure_without_weight_needs_review(d):
    [line] = build_draft("Суп", ["3 веточки укропа"], d, servings=1).lines
    assert line.ingredient_id == "dill" and line.needs_review and line.reason == REASON_UNIT_UNKNOWN


def test_can_is_canonical_piece(d):
    [line] = build_draft("Салат", ["1 банка кукурузы"], d, servings=1).lines
    assert (line.qty_per_serving, line.unit, line.needs_review) == (1, "pcs", False)


def test_to_taste_list_is_split(d):
    lines = build_draft(
        "Суп", ["Соль, перец — по вкусу", "Соль и перец по вкусу"], d, servings=2
    ).lines
    assert [(x.ingredient_id, x.optional, x.qty_per_serving) for x in lines] == [
        ("salt", True, 0),
        ("pepper", True, 0),
        ("salt", True, 0),
        ("pepper", True, 0),
    ]
    assert all(x.raw_text.startswith("Соль") for x in lines)


def test_list_with_quantity_is_not_split(d):
    [line] = build_draft("Суп", ["Соль, перец — 1 ч. л."], d, servings=1).lines
    assert line.name == "соль"


def test_review_reasons(d):
    lines = build_draft(
        "Тест", ["Масло — 20 г", "Ананас — 1 шт.", "Укроп", "200 г"], d, servings=1
    ).lines
    assert [(x.reason, x.needs_review) for x in lines] == [
        (REASON_AMBIGUOUS, True),
        (REASON_NO_MATCH, True),
        (REASON_NO_QUANTITY, True),
        ("no_name", True),
    ]
    assert lines[0].candidates == ("butter", "oil")


def test_unknown_servings_default_to_one_with_warning(d):
    draft = build_draft("Без порций", ["Мука — 200 г"], d)
    assert draft.default_servings == 1 and draft.warnings == (WARNING_SERVINGS_UNKNOWN,)
    assert draft.lines[0].qty_per_serving == 200


def test_no_ingredients_warning(d):
    draft = build_draft("  Пусто  ", [], d, servings=2)
    assert draft.title == "Пусто" and draft.warnings == (WARNING_NO_INGREDIENTS,)


def test_to_recipe_input_matches_contract(d):
    draft = build_draft(
        "Блины", ["Мука — 200 г", "Ананас — 1 шт."], d, servings=2, source_url="https://x.test/r"
    )
    body = draft.to_recipe_input()
    assert body["status"] == "draft" and body["default_servings"] == 2
    assert body["source_url"] == "https://x.test/r" and body["tags"] == []
    assert body["ingredients"][0] == {
        "ingredient_id": "flour",
        "qty_per_serving": 100,
        "unit": "g",
        "optional": False,
        "raw_text": "Мука — 200 г",
        "needs_review": False,
    }
    assert body["ingredients"][1]["ingredient_id"] is None
    assert body["ingredients"][1]["needs_review"] is True


def test_single_to_taste_line_is_not_split(d):
    [line] = build_draft("Суп", ["Соль по вкусу"], d, servings=2).lines
    assert (line.ingredient_id, line.optional, line.needs_review) == ("salt", True, False)
