import json
from collections import defaultdict

import pytest

from importers.directory import (
    CONFIDENCE_CONTAINED,
    CONFIDENCE_EXACT,
    CONFIDENCE_TIEBREAK,
    DEFAULT_PATH,
    Directory,
    Ingredient,
    load_directory,
)
from importers.text import stems
from importers.units import UNIT_DEFS

RAW = json.loads(DEFAULT_PATH.read_text("utf-8"))


@pytest.fixture(scope="module")
def directory():
    return load_directory()


# --- целостность данных справочника ---


def test_directory_size_and_unique_ids(directory):
    assert 300 <= len(directory) <= 500
    assert len({x["id"] for x in RAW}) == len(RAW)


def test_no_two_ingredients_share_an_alias():
    # одинаковые основы у разных ингредиентов дали бы вечную ничью при сопоставлении
    owners = defaultdict(set)
    for x in RAW:
        for alias in [x["name"], *x["synonyms"]]:
            owners[stems(alias)].add(x["id"])
    clashes = {tuple(sorted(k)): v for k, v in owners.items() if len(v) > 1}
    assert clashes == {}


def test_every_item_is_well_formed():
    for x in RAW:
        assert x["id"].isascii() and x["id"] == x["id"].lower(), x["id"]
        assert x["name"] and x["group"], x["id"]
        if "piece_weight_g" in x:
            assert x["piece_weight_g"] > 0, x["id"]
        for unit, weight in x.get("unit_weights_g", {}).items():
            assert unit in UNIT_DEFS and UNIT_DEFS[unit].base == "pcs", (x["id"], unit)
            assert weight > 0, x["id"]


# --- сопоставление на реальном справочнике ---


@pytest.mark.parametrize(
    ("name", "ingredient_id"),
    [
        ("моркови", "carrot"),
        ("лука", "onion"),
        ("лук репчатый", "onion"),
        ("зеленый лук", "green_onion"),
        ("лук-порей", "leek"),
        ("сливочного масла", "butter"),
        ("масло растительное", "sunflower_oil"),
        ("перца черного молотого", "black_pepper"),
        ("перец болгарский", "bell_pepper"),
        ("красный перец чили", "chili_pepper"),
        ("помидоры черри", "cherry_tomato"),
        ("помидоров", "tomato"),
        ("томаты в собственном соку", "canned_tomatoes"),
        ("сыр фета", "feta"),
        ("сыра", "hard_cheese"),
        ("яиц", "egg"),
        ("фарш говяжий", "minced_beef"),
        ("фарша", "minced_mixed"),
        ("сока лимона", "lemon_juice"),
        ("лимона", "lemon"),
        ("паприка", "paprika"),
        ("салями", "smoked_sausage"),
        ("сало", "salo"),
    ],
)
def test_match_real_names(directory, name, ingredient_id):
    assert directory.match(name).ingredient_id == ingredient_id


def test_match_ambiguous_returns_candidates(directory):
    m = directory.match("масло")
    assert m.ingredient_id is None and m.ambiguous
    assert len(m.candidates) > 1


# --- поведение на маленьком справочнике ---


@pytest.fixture
def small():
    return Directory(
        [
            Ingredient("butter", "масло сливочное"),
            Ingredient("oil", "масло растительное", ("подсолнечное масло",)),
            Ingredient("milk", "молоко"),
            Ingredient("salt", "соль"),
        ]
    )


def test_exact_and_contained_confidence(small):
    exact = small.match("молоко")
    assert (exact.ingredient_id, exact.confidence, exact.alias) == (
        "milk",
        CONFIDENCE_EXACT,
        "молоко",
    )
    contained = small.match("молоко пастеризованное")
    assert (contained.ingredient_id, contained.confidence) == ("milk", CONFIDENCE_CONTAINED)


def test_longest_alias_wins(small):
    assert small.match("подсолнечного масла").ingredient_id == "oil"


def test_no_match_lists_overlapping_candidates(small):
    m = small.match("масло")
    assert m.ingredient_id is None and m.candidates == ("butter", "oil")
    none = small.match("ананас")
    assert none.ingredient_id is None and none.candidates == () and not none.ambiguous


def test_empty_name(small):
    m = small.match("  2 % ")
    assert (m.ingredient_id, m.confidence) == (None, 0.0)


def test_tie_is_broken_by_position_but_marked_uncertain():
    d = Directory([Ingredient("a", "соль"), Ingredient("b", "перец")])
    m = d.match("соль перец")  # оба подошли одинаково: побеждает тот, что стоит раньше
    assert (m.ingredient_id, m.confidence, m.candidates) == ("a", CONFIDENCE_TIEBREAK, ("a", "b"))
    assert m.tie and m.uncertain and not m.ambiguous and m.alias == "соль"
    assert d.match("перец соль").ingredient_id == "b"


def test_tie_at_the_same_position_is_ambiguous():
    # «масло» одинаково объясняется и сливочным, и растительным
    d = Directory([Ingredient("a", "масло сливочное"), Ingredient("b", "масло растительное")])
    m = d.match("масло")
    assert m.ingredient_id is None and m.ambiguous and m.candidates == ("a", "b")


def test_partial_overlap_is_not_ambiguity():
    # «говяжья грудинка» объясняется кандидатами лишь наполовину: просто нет в справочнике
    d = Directory([Ingredient("a", "говяжья печень"), Ingredient("b", "говяжья вырезка")])
    m = d.match("говяжья грудинка")
    assert m.ingredient_id is None and not m.ambiguous and not m.tie
    assert m.candidates == ("a", "b")


def test_flour_for_dough_is_flour_not_dough(directory):
    m = directory.match("мука с горкой + 2-4 ст. л. для раскатывания теста и панировки сырников")
    assert (m.ingredient_id, m.confidence, m.uncertain) == (
        "wheat_flour",
        CONFIDENCE_TIEBREAK,
        True,
    )
    assert set(m.candidates) >= {"wheat_flour", "yeast_dough"}


def test_raw_is_not_cheese(directory):
    assert directory.match("сырых желтка").ingredient_id == "egg_yolk"
    assert directory.match("сырой картофель").ingredient_id == "potato"
    assert directory.match("сыр").ingredient_id == "hard_cheese"  # сам «сыр» не потерян


def test_directory_api(small):
    assert "milk" in small and "nope" not in small
    assert small.get("salt").name == "соль"
    assert small.get("salt").aliases == ("соль",)


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        Directory([Ingredient("a", "соль"), Ingredient("a", "перец")])


def test_alias_without_meaningful_words_is_ignored():
    d = Directory([Ingredient("x", "для")])
    assert d.match("для").ingredient_id is None


def test_full_tie_at_the_same_position_is_ambiguous():
    d = Directory([Ingredient("a", "перец чёрный"), Ingredient("b", "перец красный")])
    m = d.match("перец чёрный красный")  # оба псевдонима целиком внутри и начинаются с «перец»
    assert m.ingredient_id is None and m.ambiguous and m.candidates == ("a", "b")


@pytest.mark.parametrize(
    ("name", "ingredient_id"),
    [
        ("язык варёный", "beef_tongue"),
        ("раки", "crayfish"),
        ("икра красная", "red_caviar"),
        ("говяжья грудинка", "beef"),
    ],
)
def test_gaps_found_on_real_pages_are_filled(directory, name, ingredient_id):
    assert directory.match(name).ingredient_id == ingredient_id
