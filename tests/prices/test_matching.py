"""Подбор товаров: жёсткие требования на эталонном наборе и проверка каждого правила."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from importers.directory import Directory, Ingredient, load_directory
from prices.matching import (
    AUTO_AT,
    CONFIRM_AT,
    Matcher,
    Rules,
    extract_variant,
    load_rules,
)
from prices.normalize import RawOffer, normalize_offer

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
KNOWN_BRANDS = [
    "Простоквашино", "Домик в деревне", "Экомилк", "Слобода", "Макфа", "Увелка", "Barilla",
    "Philadelphia", "Alpen Gold", "Окское", "Петелинка", "Мираторг", "Помидорка", "Parmalat",
    "Monini",
]  # fmt: skip
GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "match_golden.json").read_text("utf-8"))
GOLDEN = {k: v for k, v in GOLDEN.items() if not k.startswith("_")}


def offer(title, category="", i=1, store="dixy", price="99", brands=KNOWN_BRANDS):
    return normalize_offer(
        RawOffer(
            store=store, external_id=str(i), title=title, price_text=price, fetched_at=NOW,
            category=category,
        ),
        brands,
    )  # fmt: skip


@pytest.fixture(scope="module")
def matcher():
    return Matcher(load_directory())


def run_golden(matcher):
    """-> {(ingredient, label, title): Match}"""
    out = {}
    for ing, sets in GOLDEN.items():
        for label, items in sets.items():
            for i, item in enumerate(items):
                title, cat = (item, "") if isinstance(item, str) else item
                out[(ing, label, title)] = matcher.match(ing, offer(title, cat, i))
    return out


# --- жёсткие требования к качеству (ADR-0007: точность важнее полноты) ---


def test_golden_no_wrong_product_is_ever_auto(matcher):
    bad_auto = [k for k, m in run_golden(matcher).items() if k[1] == "bad" and m.verdict == "auto"]
    assert bad_auto == []


def test_golden_auto_precision_is_100_percent(matcher):
    auto = [(k, m) for k, m in run_golden(matcher).items() if m.verdict == "auto"]
    assert len(auto) >= 80
    assert all(k[1] == "ok" for k, _ in auto)


def test_golden_recall_thresholds(matcher):
    ok = [m for k, m in run_golden(matcher).items() if k[1] == "ok"]
    accepted = sum(m.accepted for m in ok) / len(ok)
    auto = sum(m.verdict == "auto" for m in ok) / len(ok)
    assert accepted >= 0.95, f"auto+confirm: {accepted:.2%}"
    assert auto >= 0.80, f"auto: {auto:.2%}"


def test_golden_few_wrong_products_reach_confirmation(matcher):
    bad = [m for k, m in run_golden(matcher).items() if k[1] == "bad"]
    on_confirm = [m for m in bad if m.verdict == "confirm"]
    assert len(on_confirm) / len(bad) <= 0.03, [m.reasons for m in on_confirm]


def test_golden_is_big_enough():
    assert len(GOLDEN) >= 30
    assert sum(len(v["ok"]) + len(v["bad"]) for v in GOLDEN.values()) >= 200
    assert all(v["ok"] and v["bad"] for v in GOLDEN.values())


# --- отдельные правила ---


@pytest.mark.parametrize(
    ("ingredient", "title", "category", "reason"),
    [
        ("milk", "Шоколад молочный Alpen Gold 85 г", "", "other:milk_chocolate"),
        ("milk", "Молоко сгущённое с сахаром 380 г", "", "other:condensed_milk"),
        ("tomato", "Томатная паста 70 г", "", "other:tomato_paste"),
        ("tomato", "Сок томатный 1 л", "", "other:tomato_juice"),
        ("hard_cheese", "Сыр Моцарелла 125 г", "", "other:mozzarella"),
        ("rice", "Рисовая лапша 200 г", "", "other:rice_noodles"),
        ("apple", "Сок яблочный 1 л", "", "no_match"),
        ("milk", "Набор для пикника 5 шт", "", "no_match"),
        ("beef", "Корм для собак с говядиной 400 г", "", "not_food"),
        ("beef", "Говядина 1 кг", "Товары для животных", "not_food"),
        ("chicken_breast", "Филе куриное копчёное 150 г", "", "form:smoked"),
        ("potato", "Картофель замороженный 450 г", "", "form:frozen"),
        ("cucumber", "Огурцы маринованные 680 г", "", "form:pickled"),
        ("onion", "Лук жареный 100 г", "", "form:fried"),
        ("salt", "Соль для ванн 1 кг", "", "excluded:ванн"),
        ("egg", "Яйцо шоколадное 20 г", "", "excluded:шоколадн"),
        ("carrot", "Морковь по-корейски 300 г", "", "dish:корейск"),
        ("sour_cream", "Пирог со сметаной 500 г", "", "not_head"),
        ("lemon", "Чай чёрный с лимоном 25 пакетиков", "", "not_head"),
        ("milk", "Молоко 1 л", "Мясо и птица", "category:мясо и птица"),
    ],
)
def test_rejections_have_reasons(matcher, ingredient, title, category, reason):
    m = matcher.match(ingredient, offer(title, category))
    assert (m.verdict, m.score, m.reasons) == ("reject", 0.0, (reason,))


def test_form_must_match_when_ingredient_itself_has_a_form(matcher):
    pickled = matcher.match("pickled_cucumbers", offer("Огурцы маринованные 680 г"))
    assert pickled.verdict == "auto"
    assert matcher.match("pickled_cucumbers", offer("Огурцы свежие 1 кг")).verdict == "reject"


def test_clean_title_is_auto_and_scores_by_category(matcher):
    plain = matcher.match("milk", offer("Молоко 1 л"))
    assert (plain.verdict, plain.score, plain.reasons) == ("auto", 0.95, ("head:clean",))
    with_cat = matcher.match("milk", offer("Молоко 1 л", "Молочные продукты"))
    assert (with_cat.score, with_cat.reasons) == (1.0, ("head:clean", "category"))
    assert matcher.match("milk", offer("Молоко 1 л", "Акции недели")).reasons == ("head:clean",)


def test_unverified_or_frozen_category_does_not_decide(matcher):
    assert matcher.match("milk", offer("Молоко 1 л", "Заморозка")).verdict == "auto"
    assert matcher.match("milk", offer("Молоко 1 л", "Что-то новое")).verdict == "auto"


def test_extra_words_lower_the_verdict(matcher):
    one = matcher.match("milk", offer("Молоко козье 1 л"))
    assert (one.verdict, one.score, one.reasons) == ("confirm", 0.75, ("head:extra1",))
    many = matcher.match("milk", offer("Молоко козье фермерское домашнее 1 л"))
    assert (many.verdict, many.reasons) == ("confirm", ("head:extra2+",))
    assert many.score == 0.6 and many.score >= CONFIRM_AT and one.score < AUTO_AT


def test_brandish_words_are_not_extra(matcher):
    # заглавная не в начале и латиница похожи на марку; в кавычках марка вырезается целиком
    assert matcher.match("milk", offer("Молоко Вкусвилл 1 л")).verdict == "auto"
    assert matcher.match("milk", offer("Молоко Vkusvill 1 л")).verdict == "auto"
    assert matcher.match("milk", offer("Молоко «Какая-то марка» 1 л")).verdict == "auto"
    assert matcher.match("milk", offer("молоко козье 1 л")).reasons == ("head:extra1",)


def test_pack_outside_plausible_range_is_penalized(matcher):
    ok = matcher.match("salt", offer("Соль поваренная 1 кг"))
    huge = matcher.match("salt", offer("Соль поваренная 50 кг"))  # >3000 г для специй
    assert (ok.verdict, huge.verdict) == ("auto", "confirm")
    assert huge.score == pytest.approx(ok.score - 0.30) and "pack" in huge.reasons
    # без фасовки или в штуках штраф не применяется
    assert matcher.match("salt", offer("Соль поваренная")).verdict == "auto"
    assert matcher.match("egg", offer("Яйцо куриное С1 10 шт")).verdict == "auto"
    # неизвестная группа берёт диапазон по умолчанию
    assert matcher.match("avocado", offer("Авокадо 1 кг")).verdict == "auto"


def test_general_ingredient_accepts_its_kinds(matcher):
    for title in ("Рис длиннозерный 900 г", "Рис круглозерный 800 г", "Рис басмати 500 г"):
        assert matcher.match("rice", offer(title)).verdict == "auto"
    # а конкретный вид общий не принимает
    assert matcher.match("rice_long", offer("Рис круглозерный 800 г")).verdict == "reject"


def test_tie_between_acceptable_kinds_is_not_capped():
    d = Directory([Ingredient("a", "соль"), Ingredient("b", "перец")])
    rules = load_rules()
    m = Matcher(d, Rules(**{**rules.__dict__, "includes": {"a": frozenset({"b"})}}))
    r = m.match("a", offer("Соль перец 100 г"))  # a и b оба допустимы для «a»
    assert r.accepted and "tie" not in r.reasons


def test_tie_with_foreign_candidate_is_capped():
    d = Directory([Ingredient("a", "соль"), Ingredient("b", "перец")])
    m = Matcher(d, load_rules())
    r = m.match("a", offer("Соль перец 100 г"))  # выбрано по положению, но b чужой
    assert r.score <= 0.55 and r.verdict == "reject" and "tie" in r.reasons


# --- вариант, марка, короткий список ---


@pytest.mark.parametrize(
    ("title", "variant"),
    [
        ("Молоко 3,2% 1 л", "3,2%"),
        ("Молоко 3.2% 1 л", "3,2%"),
        ("Молоко цельное 3,4-4,5% 1 л", "3,4-4,5%"),
        ("Сметана 20 % 300 г", "20%"),
        ("Молоко 1 л", ""),
        ("", ""),
    ],
)
def test_extract_variant(title, variant):
    assert extract_variant(title) == variant


def test_match_carries_brand_variant_and_ids(matcher):
    m = matcher.match("milk", offer("Молоко «Простоквашино» 3,2% 930 мл", i=7, store="lenta"))
    assert (m.ingredient_id, m.store, m.external_id) == ("milk", "lenta", "7")
    assert (m.brand, m.variant, m.accepted) == ("Простоквашино", "3,2%", True)


def test_shortlist_keeps_diversity_and_drops_rejects(matcher):
    offers = [
        offer("Молоко «Простоквашино» 3,2% 930 мл", i=1),
        offer("Молоко «Простоквашино» 3,2% 1,5 л", i=2),
        offer("Молоко «Простоквашино» 3,2% 200 мл", i=3),  # третья фасовка той же марки/варианта
        offer("Молоко «Простоквашино» 1,5% 930 мл", i=4),  # другой вариант
        offer("Молоко «Экомилк» 3,2% 930 мл", i=5),  # другая марка
        offer("Шоколад молочный 85 г", i=6),  # отказ
        offer("Молоко «Простоквашино» 3,2% 930 мл", i=7, store="lenta"),  # другой магазин
    ]
    result = matcher.shortlist("milk", offers)
    ids = [(m.store, m.brand, m.variant, m.external_id) for m in result]
    assert ("dixy", "Простоквашино", "3,2%", "3") not in ids
    assert len(ids) == 5 and all(m.accepted for m in result)
    assert {m.external_id for m in result} == {"1", "2", "4", "5", "7"}


def test_shortlist_limit_and_order(matcher):
    offers = [offer(f"Молоко «Марка{i}» 3,2% 1 л", i=i) for i in range(20)]
    offers.append(offer("Молоко козье 1 л", i=99))
    result = matcher.shortlist("milk", offers, limit=5)
    assert len(result) == 5
    assert [m.score for m in result] == sorted((m.score for m in result), reverse=True)
    assert all(m.external_id != "99" for m in result)  # confirm хуже auto и не попал в топ-5


def test_shortlist_empty_when_nothing_matches(matcher):
    assert matcher.shortlist("milk", [offer("Шоколад 85 г")]) == []
    assert matcher.shortlist("milk", []) == []


def test_load_rules_shape():
    r = load_rules()
    assert "rice_long" in r.includes["rice"] and r.default_pack_range == (1, 50000)
    assert r.pack_ranges["специи"] == (1, 3000) and "заморо" in r.any_category
    assert r.dish_stems and r.harmless and r.non_food


@pytest.mark.parametrize(
    "category", ["Заморозка", "Замороженные продукты", "заморозка и мороженое"]
)
def test_frozen_category_matches_any_group(matcher, category):
    # раздел заморозки в магазине содержит продукты любой группы
    assert matcher._category("молочные", category.lower()) == "unknown"
    assert matcher._category("овощи", category.lower()) == "unknown"
