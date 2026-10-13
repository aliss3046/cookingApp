"""Стартовый набор блюд: сборка строго, файл не отстаёт от источника, данные правдоподобны."""

import json

import pytest

import importers.seed_recipes as seed_mod
from importers.directory import Directory, Ingredient, load_directory
from importers.seed_recipes import SeedError, build_seed, dumps, main

SOURCE = json.loads(seed_mod.SOURCE.read_text("utf-8"))
SEED = json.loads(seed_mod.OUTPUT.read_text("utf-8"))

# Словарь тегов закрытый: опечатка в теге («ужен») ломает фильтры на клиенте.
TAGS = {
    "завтрак", "обед", "ужин", "суп", "салат", "десерт", "выпечка", "быстро", "праздничное",
    "духовка", "вегетарианское", "мясо", "курица", "рыба", "яйца", "творог", "грибы", "рис",
    "паста", "овощи",
}  # fmt: skip


@pytest.fixture(scope="module")
def directory():
    return load_directory()


def test_committed_file_matches_the_source(directory):
    assert seed_mod.OUTPUT.read_text("utf-8") == dumps(build_seed(SOURCE, directory))


def test_set_has_30_to_50_dishes_with_unique_slugs():
    assert 30 <= len(SEED) <= 50
    assert len({r["slug"] for r in SEED}) == len(SEED)
    assert len({r["title"] for r in SEED}) == len(SEED)


def test_every_dish_is_complete(directory):
    for r in SEED:
        assert r["status"] == "confirmed" and 1 <= r["default_servings"] <= 12, r["slug"]
        assert r["tags"] and set(r["tags"]) <= TAGS, (r["slug"], set(r["tags"]) - TAGS)
        required = [i for i in r["ingredients"] if not i["optional"]]
        assert len(required) >= 3, r["slug"]
        for i in r["ingredients"]:
            assert i["ingredient_id"] in directory, (r["slug"], i["raw_text"])
            assert i["unit"] in {"g", "ml", "pcs"} and i["qty_per_serving"] >= 0
            assert (i["qty_per_serving"] == 0) == i["optional"], (r["slug"], i["raw_text"])


def test_mass_per_serving_is_plausible(directory):
    # грубая защита от опечаток: 5000 г вместо 500 или 5 г вместо 500
    for r in SEED:
        total = 0.0
        for i in r["ingredients"]:
            qty = i["qty_per_serving"]
            if i["unit"] == "pcs":
                qty *= directory.get(i["ingredient_id"]).piece_weight_g or 0
            total += qty
        assert 100 <= total <= 900, (r["slug"], round(total))


def test_to_taste_lists_are_split_into_optional_lines():
    omelet = next(r for r in SEED if r["slug"] == "eggs_tomatoes")
    optional = [i["ingredient_id"] for i in omelet["ingredients"] if i["optional"]]
    assert optional == ["salt", "black_pepper"]


def test_known_dish_is_exact(directory):
    borsch = next(r for r in SEED if r["slug"] == "borsch")
    by_id = {i["ingredient_id"]: i for i in borsch["ingredients"]}
    assert borsch["default_servings"] == 6
    assert by_id["beef"]["qty_per_serving"] == 100  # 600 г на 6 порций
    assert by_id["garlic"]["qty_per_serving"] == 2.5  # 3 зубчика = 15 г на 6 порций
    assert by_id["tomato_paste"]["unit"] == "ml" and by_id["tomato_paste"]["qty_per_serving"] == 5


# --- строгость сборки ---


@pytest.fixture
def small():
    return Directory([Ingredient("flour", "мука"), Ingredient("egg", "яйцо куриное", ("яйцо",))])


def dish(**kw):
    base = {
        "slug": "x",
        "title": "Х",
        "servings": 2,
        "tags": ["завтрак"],
        "lines": ["Мука — 200 г"],
    }
    return {**base, **kw}


def test_build_seed_ok(small):
    [r] = build_seed([dish()], small)
    assert r["ingredients"][0] == {
        "ingredient_id": "flour",
        "qty_per_serving": 100,
        "unit": "g",
        "optional": False,
        "raw_text": "Мука — 200 г",
    }


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (dish(lines=["Космическая пыль — 3 г"]), "no_match"),
        (dish(lines=["Мука"]), "no_quantity"),
        (dish(lines=["200 г"]), "no_name"),
        (dish(servings=0), "порций 0"),
        (dish(servings=99), "порций 99"),
        (dish(tags=[]), "нет тегов"),
        (dish(lines=[]), "no_ingredients"),
    ],
)
def test_build_seed_fails_loudly(small, bad, message):
    with pytest.raises(SeedError, match=message):
        build_seed([bad], small)


def test_build_seed_rejects_duplicate_slug(small):
    with pytest.raises(SeedError, match="повторяющийся slug"):
        build_seed([dish(), dish(title="Другое")], small)


def test_build_seed_collects_all_problems(small):
    with pytest.raises(SeedError) as e:
        build_seed([dish(slug="a", tags=[]), dish(slug="b", lines=["Космос — 1 г"])], small)
    assert "a: нет тегов" in str(e.value) and "b:" in str(e.value)


# --- командная строка ---


@pytest.fixture
def paths(tmp_path, monkeypatch):
    src, out = tmp_path / "source.json", tmp_path / "recipes.json"
    monkeypatch.setattr(seed_mod, "SOURCE", src)
    monkeypatch.setattr(seed_mod, "OUTPUT", out)
    monkeypatch.setattr(seed_mod, "load_directory", lambda: load_directory())
    return src, out


def write_source(path, lines):
    path.write_text(json.dumps([dish(lines=lines)], ensure_ascii=False), encoding="utf-8")


def test_cli_writes_then_checks(paths, capsys):
    src, out = paths
    write_source(src, ["Мука пшеничная — 200 г"])
    assert main([]) == 0 and "Записано 1 блюд" in capsys.readouterr().out
    assert json.loads(out.read_text("utf-8"))[0]["slug"] == "x"
    assert main(["--check"]) == 0 and "актуален" in capsys.readouterr().out


def test_cli_check_detects_stale_and_missing_file(paths, capsys):
    src, _ = paths
    write_source(src, ["Мука пшеничная — 200 г"])
    assert main(["--check"]) == 1 and "устарел" in capsys.readouterr().out  # файла нет
    main([])
    write_source(src, ["Мука пшеничная — 300 г"])
    assert main(["--check"]) == 1 and "устарел" in capsys.readouterr().out


def test_cli_reports_bad_source(paths, capsys):
    src, out = paths
    write_source(src, ["Космическая пыль — 3 г"])
    assert main([]) == 1
    assert "не собран" in capsys.readouterr().err and not out.exists()
