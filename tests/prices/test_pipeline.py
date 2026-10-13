from datetime import UTC, datetime

import pytest
from payloads import card, page_with

from importers.directory import load_directory
from importers.errors import FetchFailed
from prices.matching import MATCHER_VERSION, Matcher
from prices.memory_store import MemoryPriceStore
from prices.pipeline import MIN_PREVIOUS_FOR_ALERT, run_store
from prices.politeness import BudgetExceeded, NotAllowed, StoreBlocked
from prices.ports import RunStats
from prices.profile import CategorySpec, StoreDisabled, StoreProfile

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
MILK_URL, VEG_URL, OTHER_URL = (f"https://shop.test/{n}" for n in ("milk", "veg", "other"))


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        item = self.pages[url]
        if isinstance(item, Exception):
            raise item
        return item


def profile(*categories, enabled=True):
    return StoreProfile(
        code="shop", name="Магазин", enabled=enabled, approval=None, base_url="https://shop.test",
        min_delay_s=20, daily_request_limit=100, categories=tuple(categories),
    )  # fmt: skip


MILK = CategorySpec(MILK_URL, groups=("молочные",))
VEG = CategorySpec(VEG_URL, ingredients=("onion", "tomato", "nope-unknown"))


@pytest.fixture(scope="module")
def directory():
    return load_directory()


def run(directory, prof, pages, store=None, **kw):
    store = store or MemoryPriceStore()
    stats = run_store(
        prof, "loc1", fetcher=FakeFetcher(pages), directory=directory,
        matcher=Matcher(directory), store=store, now=NOW, **kw,
    )  # fmt: skip
    return stats, store


MILK_PAGE = page_with(
    [
        card("m1", "Молоко «Простоквашино» 3,2% 930 мл", "89.99"),
        card("m2", "Молоко «Экомилк» 3,2% 930 мл", "79.99"),
        card("c1", "Сыр Российский 50% 200 г", "199.99"),
        card("x1", "Шоколад молочный 85 г", "99.99"),
        card("z1", "Без цены", ""),
    ]
)
VEG_PAGE = page_with(
    [
        card("o1", "Лук репчатый", "37.09", unit="700г", unit_price=5299),
        card("t1", "Помидоры красные", "199.00", unit="1кг", unit_price=19900),
    ]
)


def test_disabled_store_is_never_read(directory):
    fetcher = FakeFetcher({})
    with pytest.raises(StoreDisabled):
        run_store(
            profile(MILK, enabled=False), "loc1", fetcher=fetcher, directory=directory,
            matcher=Matcher(directory), store=MemoryPriceStore(), now=NOW,
        )  # fmt: skip
    assert fetcher.calls == []


def test_full_run_writes_products_prices_and_mapping(directory):
    stats, store = run(directory, profile(MILK, VEG), {MILK_URL: MILK_PAGE, VEG_URL: VEG_PAGE})
    assert (stats.pages, stats.offers_found, stats.parsed, stats.parse_errors) == (2, 7, 6, 1)
    assert stats.written and stats.suspicious is None and stats.blocked is None
    assert {k[1] for k in store.products} == {"m1", "m2", "c1", "x1", "o1", "t1"}
    assert len(store.prices) == 6 and all(loc == "loc1" for _, loc, _ in store.prices)

    milk_matches, version = store.mapping[("shop", "milk")]
    assert version == MATCHER_VERSION
    assert [m.external_id for m in milk_matches] == ["m1", "m2"]  # шоколад не подобран
    cheese, _ = store.mapping[("shop", "hard_cheese")]
    assert [m.external_id for m in cheese] == ["c1"]
    onion, _ = store.mapping[("shop", "onion")]
    assert onion[0].verdict == "auto" and onion[0].external_id == "o1"
    # «Помидоры красные» — лишнее слово «красные», поэтому confirm, а не auto
    assert stats.matched_auto >= 4 and stats.matched_confirm == 1
    # пустой результат группы тоже записан: данные свежие, старое сопоставление не должно жить
    assert ("shop", "kefir") in store.mapping and store.mapping[("shop", "kefir")][0] == ()
    assert ("shop", "nope-unknown") not in store.mapping  # неизвестный ингредиент пропущен


def test_prices_are_append_only_across_runs(directory):
    store = MemoryPriceStore()
    run(directory, profile(MILK), {MILK_URL: MILK_PAGE}, store=store)
    run(directory, profile(MILK), {MILK_URL: MILK_PAGE}, store=store)
    assert len(store.prices) == 8 and len(store.products) == 4  # цены копятся, товары обновляются
    assert len(store.runs) == 2


def test_blocked_store_stops_and_writes_nothing(directory):
    pages = {
        MILK_URL: MILK_PAGE,
        VEG_URL: StoreBlocked("HTTP 403", status=403),
        OTHER_URL: MILK_PAGE,
    }
    stats, store = run(
        directory,
        profile(
            MILK,
            CategorySpec(VEG_URL, groups=("овощи",)),
            CategorySpec(OTHER_URL, groups=("мясо",)),
        ),
        pages,
    )
    assert stats.blocked == "HTTP 403" and not stats.written
    assert stats.pages == 1  # после блокировки дальше не идём
    assert store.products == {} and store.prices == [] and store.mapping == {}
    assert store.runs == [stats]


def test_budget_exhaustion_stops_without_writing(directory):
    stats, store = run(
        directory, profile(MILK, VEG), {MILK_URL: BudgetExceeded("лимит"), VEG_URL: VEG_PAGE}
    )
    assert stats.budget_exceeded and not stats.written and store.prices == []


def test_robots_forbidden_category_is_skipped_others_continue(directory):
    stats, store = run(
        directory, profile(MILK, VEG), {MILK_URL: NotAllowed("no"), VEG_URL: VEG_PAGE}
    )
    assert stats.skipped_by_robots == 1 and stats.pages == 1 and stats.written
    assert {k[1] for k in store.products} == {"o1", "t1"}


def test_failed_page_is_noted_and_run_continues(directory):
    stats, _ = run(
        directory, profile(MILK, VEG), {MILK_URL: FetchFailed("HTTP 500"), VEG_URL: VEG_PAGE}
    )
    assert stats.pages == 1 and stats.written and "HTTP 500" in stats.notes[0]


def test_unrecognised_page_format_is_suspicious_and_not_written(directory):
    stats, store = run(directory, profile(MILK), {MILK_URL: "<html>переверстали</html>"})
    assert stats.parsed == 0 and "формат страниц" in stats.suspicious and not stats.written
    assert store.products == {}


def test_big_drop_in_parsed_cards_is_suspicious(directory):
    store = MemoryPriceStore()
    store.save_run(
        RunStats(store="shop", location_key="loc1", started_at=NOW, parsed=20, written=True)
    )
    stats, store = run(directory, profile(MILK), {MILK_URL: MILK_PAGE}, store=store)  # 4 против 20
    assert "против 20" in stats.suspicious and not stats.written and store.prices == []


def test_small_drop_or_small_history_is_fine(directory):
    ok_prev = RunStats(store="shop", location_key="loc1", started_at=NOW, parsed=5, written=True)
    store = MemoryPriceStore()
    store.save_run(ok_prev)  # прошлый запуск меньше порога: сравнивать нечего
    assert MIN_PREVIOUS_FOR_ALERT > 5
    stats, _ = run(directory, profile(MILK), {MILK_URL: MILK_PAGE}, store=store)
    assert stats.written and stats.suspicious is None
    store2 = MemoryPriceStore()
    store2.save_run(
        RunStats(store="shop", location_key="loc1", started_at=NOW, parsed=5 + 10, written=True)
    )
    stats2, _ = run(
        directory, profile(MILK), {MILK_URL: MILK_PAGE}, store=store2
    )  # 4 из 15: падение 73%
    assert stats2.suspicious


def test_last_run_ignores_unwritten_and_other_addresses(directory):
    store = MemoryPriceStore()
    store.save_run(
        RunStats(store="shop", location_key="loc1", started_at=NOW, parsed=3, suspicious="x")
    )
    store.save_run(
        RunStats(store="shop", location_key="loc2", started_at=NOW, parsed=9, written=True)
    )
    assert store.last_run("shop", "loc1") is None
    assert store.last_run("shop", "loc2").parsed == 9


def test_known_brands_are_passed_to_normalization(directory):
    page = page_with([card("m1", "Молоко Домик в деревне 1,5% 950 мл", "70")])
    _, store = run(directory, profile(MILK), {MILK_URL: page}, known_brands=["Домик в деревне"])
    assert store.products[("shop", "m1")].brand == "Домик в деревне"
    match = store.mapping[("shop", "milk")][0][0]
    assert match.verdict == "auto"  # марка известна, лишних слов нет


def test_now_defaults_to_current_time(directory):
    store = MemoryPriceStore()
    stats = run_store(
        profile(MILK), "loc1", fetcher=FakeFetcher({MILK_URL: MILK_PAGE}), directory=directory,
        matcher=Matcher(directory), store=store,
    )  # fmt: skip
    assert stats.finished_at >= stats.started_at and stats.written


def test_unreadable_price_is_counted_as_parse_error(directory, monkeypatch):
    import prices.pipeline as pipeline
    from prices.normalize import PriceParseError, normalize_offer

    def flaky(raw, brands=()):
        if raw.external_id == "m2":
            raise PriceParseError("плохая цена")
        return normalize_offer(raw, brands)

    monkeypatch.setattr(pipeline, "normalize_offer", flaky)
    stats, store = run(directory, profile(MILK), {MILK_URL: MILK_PAGE})
    assert stats.parse_errors == 2 and stats.parsed == 3  # «Без цены» и m2
    assert ("shop", "m2") not in store.products
