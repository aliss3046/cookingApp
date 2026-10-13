import io
import json
from pathlib import Path
from typing import ClassVar

import pytest
from payloads import card, nuxt_page, page_with

import prices.__main__ as cli
from importers.directory import load_directory
from prices.politeness import StoreBlocked
from prices.profile import Approval, CategorySpec, StoreProfile

PAGE = page_with(
    [
        card("m1", "Молоко «Простоквашино» 3,2% 930 мл", "89.99"),
        card("o1", "Лук репчатый", "37.09", unit="700г", unit_price=5299),
        card("x1", "Шоколад молочный 85 г", "99.99"),
        card("bad", "Без цены", ""),
    ]
)


@pytest.fixture(scope="module")
def directory():
    return load_directory()


def call(argv, directory, profiles=None):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, directory=directory, profiles=profiles, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_dry_run_prints_parsed_products_and_shortlists(tmp_path, directory):
    f = tmp_path / "page.html"
    f.write_text(PAGE, encoding="utf-8")
    code, out, err = call(
        ["dry-run", "--store", "magnit", "--html", str(f), "--groups", "молочные, овощи",
         "--ingredients", "milk,nope"],
        directory,
    )  # fmt: skip
    assert (code, err) == (cli.EXIT_OK, "")
    data = json.loads(out)
    assert (data["strategy"], data["cards"], data["skipped"], data["price_errors"]) == (
        "nuxt",
        3,
        1,
        0,
    )
    ids = {p["id"] for p in data["products"]}
    assert ids == {"m1", "o1", "x1"}
    onion = next(p for p in data["products"] if p["id"] == "o1")
    assert (onion["mode"], onion["price_per_kg"]) == ("by_weight", "52.99")
    assert [m["external_id"] for m in data["shortlists"]["milk"]] == ["m1"]
    assert data["shortlists"]["onion"][0]["verdict"] == "auto"
    assert "nope" not in data["shortlists"]


def test_dry_run_counts_bad_price_text(tmp_path, directory):
    page = page_with([card("1", "Молоко 1 л", "бесплатно")])
    f = tmp_path / "p.html"
    f.write_text(page, encoding="utf-8")
    _, out, _ = call(["dry-run", "--store", "x", "--html", str(f)], directory)
    assert json.loads(out)["cards"] == 0  # нечитаемая цена отброшена ещё при разборе карточки


def test_dry_run_counts_price_errors_from_normalization(tmp_path, directory, monkeypatch):
    def broken(raw):
        raise cli.PriceParseError("плохая цена")

    monkeypatch.setattr(cli, "normalize_offer", broken)
    f = tmp_path / "p.html"
    f.write_text(PAGE, encoding="utf-8")
    _, out, _ = call(["dry-run", "--store", "x", "--html", str(f)], directory)
    assert json.loads(out)["price_errors"] == 3 and json.loads(out)["products"] == []


def test_categories_lists_the_tree(tmp_path, directory):
    tree = {
        "c": [
            {
                "code": "milk",
                "name": "Молоко",
                "children": [{"code": "kefir", "name": "Кефир", "children": []}],
            }
        ]
    }
    f = tmp_path / "p.html"
    f.write_text(nuxt_page(tree), encoding="utf-8")
    code, out, _ = call(["categories", "--html", str(f)], directory)
    assert code == 0 and out == "-milk\tМолоко\n  -kefir\tКефир\n"


def profile(enabled=True, categories=()):
    return StoreProfile(
        code="shop", name="Магазин", enabled=enabled,
        approval=Approval("владелец", "2026-10-14", "решение") if enabled else None,
        base_url="https://shop.test", min_delay_s=20, daily_request_limit=50,
        categories=tuple(categories),
    )  # fmt: skip


def test_run_refuses_disabled_unknown_and_broken_profiles(directory):
    code, out, err = call(
        ["run", "--store", "shop", "--location", "1"], directory, {"shop": profile(False)}
    )
    assert (code, out) == (cli.EXIT_FAILED, "") and "выключен" in err
    code, _, err = call(
        ["run", "--store", "zzz", "--location", "1"], directory, {"shop": profile()}
    )
    assert code == cli.EXIT_FAILED and "Нет профиля магазина «zzz»" in err

    def boom():
        raise cli.ProfileError("битый файл")

    cli.load_profiles, saved = boom, cli.load_profiles
    try:
        code, _, err = call(["run", "--store", "shop", "--location", "1"], directory)
    finally:
        cli.load_profiles = saved
    assert code == cli.EXIT_FAILED and "битый файл" in err


class FakeFetcher:
    pages: ClassVar[dict] = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def get(self, url):
        item = self.pages[url]
        if isinstance(item, Exception):
            raise item
        return item


def test_run_prints_stats_and_shortlists(directory, monkeypatch):
    FakeFetcher.pages = {"https://shop.test/milk": PAGE}
    monkeypatch.setattr(cli, "PoliteFetcher", FakeFetcher)
    prof = profile(
        categories=[CategorySpec("https://shop.test/milk", groups=("молочные", "овощи"))]
    )
    code, out, err = call(
        ["run", "--store", "shop", "--location", "992301"], directory, {"shop": prof}
    )
    assert (code, err) == (cli.EXIT_OK, "")
    data = json.loads(out)
    assert data["stats"]["written"] is True and data["stats"]["parsed"] == 3
    assert [m["external_id"] for m in data["shortlists"]["milk"]] == ["m1"]


def test_run_writes_json_file_and_fails_on_block(directory, monkeypatch, tmp_path):
    FakeFetcher.pages = {"https://shop.test/milk": StoreBlocked("HTTP 403", status=403)}
    monkeypatch.setattr(cli, "PoliteFetcher", FakeFetcher)
    prof = profile(categories=[CategorySpec("https://shop.test/milk", groups=("молочные",))])
    target = tmp_path / "result.json"
    code, out, _ = call(
        ["run", "--store", "shop", "--location", "1", "--json", str(target)],
        directory,
        {"shop": prof},
    )
    assert code == cli.EXIT_FAILED and out == ""  # заблокирован: код возврата 1
    assert json.loads(target.read_text("utf-8"))["stats"]["blocked"] == "HTTP 403"


def test_fetcher_gets_the_profile_limits(directory, monkeypatch):
    created = []

    class Spy(FakeFetcher):
        def __init__(self, **kwargs):
            created.append(kwargs)

    FakeFetcher.pages = {}
    monkeypatch.setattr(cli, "PoliteFetcher", Spy)
    call(["run", "--store", "shop", "--location", "1"], directory, {"shop": profile()})
    assert created == [{"min_delay_s": 20, "daily_limit": 50}]


def test_run_loads_shipped_profiles_when_none_given(directory, monkeypatch):
    class Blocked:
        def __init__(self, **_):
            pass

        def get(self, url):
            raise StoreBlocked("HTTP 403", status=403)  # сеть в тестах не трогаем

    monkeypatch.setattr(cli, "PoliteFetcher", Blocked)
    code, out, _ = call(["run", "--store", "dixy", "--location", "1"], directory)
    assert code == cli.EXIT_FAILED and json.loads(out)["stats"]["blocked"] == "HTTP 403"


def test_run_from_saved_pages_needs_no_network(directory, tmp_path, monkeypatch):
    def no_network(**_):
        raise AssertionError("сеть не должна использоваться")

    monkeypatch.setattr(cli, "PoliteFetcher", no_network)
    html = Path(__file__).parent / "fixtures" / "dixy_cards.html"
    (tmp_path / "catalog_onion.html").write_text(html.read_text("utf-8"), encoding="utf-8")
    prof = profile(categories=[CategorySpec("https://shop.test/catalog/onion", groups=("овощи",))])
    code, out, _ = call(
        ["run", "--store", "shop", "--location", "1", "--pages-dir", str(tmp_path)],
        directory,
        {"shop": prof},
    )
    data = json.loads(out)
    assert code == cli.EXIT_OK and data["stats"]["pages"] == 1 and data["stats"]["parsed"] == 3
    assert "onion" in data["shortlists"]


def test_profile_source_picks_the_fetcher(tmp_path):
    from dataclasses import replace

    from prices.fetcher import PoliteFetcher
    from prices.saved_pages import SavedPages

    http = profile()
    assert isinstance(cli._fetcher(http, None), PoliteFetcher)
    saved = replace(http, source="saved", pages_dir=str(tmp_path))
    assert isinstance(cli._fetcher(saved, None), SavedPages)
    assert isinstance(cli._fetcher(http, str(tmp_path)), SavedPages)  # --pages-dir главнее
