from dataclasses import replace

import pytest

from importers.errors import FetchFailed
from prices import sources
from prices.fetcher import PoliteFetcher
from prices.politeness import BudgetExceeded, NotAllowed, StoreBlocked
from prices.profile import StoreProfile
from prices.saved_pages import SavedPages
from prices.sources import ChainFetcher, build_fetcher, register_source


class Stub:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def get(self, url):
        self.calls += 1
        out = self.outcomes[min(self.calls, len(self.outcomes)) - 1]
        if isinstance(out, Exception):
            raise out
        return out


BLOCK = StoreBlocked("HTTP 403", status=403)


def test_first_working_source_wins():
    a, b = Stub("A"), Stub("B")
    assert ChainFetcher([("a", a), ("b", b)]).get("u") == "A" and b.calls == 0


def test_blocked_source_is_retired_and_next_one_takes_over():
    a, b = Stub(BLOCK), Stub("B")
    chain = ChainFetcher([("a", a), ("b", b)])
    assert chain.get("u1") == "B" and chain.get("u2") == "B"
    assert a.calls == 1 and b.calls == 2  # заблокированный источник больше не трогаем


def test_fetch_failure_moves_on_without_retiring_the_source():
    a, b = Stub(FetchFailed("нет файла"), "A2"), Stub("B")
    chain = ChainFetcher([("a", a), ("b", b)])
    assert chain.get("u1") == "B" and chain.get("u2") == "A2"


def test_all_failed_raises_last_error_and_dead_chain_raises_block():
    chain = ChainFetcher([("a", Stub(BLOCK)), ("b", Stub(FetchFailed("нет")))])
    with pytest.raises(FetchFailed):
        chain.get("u")
    only = ChainFetcher([("a", Stub(BLOCK))])
    with pytest.raises(StoreBlocked):
        only.get("u1")
    with pytest.raises(StoreBlocked):
        only.get("u2")  # живых источников не осталось


@pytest.mark.parametrize("stop", [NotAllowed("robots"), BudgetExceeded("лимит")])
def test_robots_and_budget_stop_the_chain_at_once(stop):
    b = Stub("B")
    with pytest.raises(type(stop)):
        ChainFetcher([("a", Stub(stop)), ("b", b)]).get("u")
    assert b.calls == 0


def profile(**kw):
    base = StoreProfile(
        code="shop", name="S", enabled=False, approval=None, base_url="https://s.test",
        min_delay_s=20, daily_request_limit=10, categories=(),
    )  # fmt: skip
    return replace(base, **kw)


def test_build_fetcher_follows_profile_sources(tmp_path):
    assert isinstance(build_fetcher(profile()), PoliteFetcher)
    saved = build_fetcher(profile(sources=("saved",), pages_dir=str(tmp_path)))
    assert isinstance(saved, SavedPages) and saved.folder == tmp_path
    assert build_fetcher(profile(sources=("saved",))).folder.as_posix() == "prices/pages/shop"
    chain = build_fetcher(profile(sources=("http", "saved")))
    assert isinstance(chain, ChainFetcher) and [n for n, _ in chain.fetchers] == ["http", "saved"]
    assert isinstance(build_fetcher(profile(), str(tmp_path)), SavedPages)  # --pages-dir главнее


def test_new_sources_plug_in_through_the_registry():
    try:
        register_source("custom", lambda p: Stub("X"))
        assert "custom" in sources.source_names()
        assert build_fetcher(profile(sources=("custom",))).get("u") == "X"
    finally:
        sources.SOURCES.pop("custom")
