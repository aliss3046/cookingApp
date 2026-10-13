"""Источники страниц: реестр загрузчиков и цепочка с откатом.

Профиль магазина перечисляет источники по порядку (`"sources": ["http", "saved"]`). Каждый
источник — объект с методом `get(url) -> html`. Реестр открыт: новый способ добычи страницы
подключается через `register_source(имя, фабрика)`, остальной конвейер (разбор, нормализация,
подбор) от источника не зависит.

В поставке два источника: `http` (вежливая загрузка по сети) и `saved` (страницы, сохранённые
человеком из браузера). Способов выдать программу за браузер в проекте нет намеренно.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from importers.errors import FetchFailed
from prices.fetcher import PoliteFetcher
from prices.politeness import StoreBlocked
from prices.saved_pages import SavedPages

if TYPE_CHECKING:
    from prices.profile import StoreProfile


class Fetcher(Protocol):
    def get(self, url: str) -> str: ...


Factory = Callable[["StoreProfile"], Fetcher]


def _http(profile: StoreProfile) -> Fetcher:
    return PoliteFetcher(min_delay_s=profile.min_delay_s, daily_limit=profile.daily_request_limit)


def _saved(profile: StoreProfile) -> Fetcher:
    return SavedPages(profile.pages_dir or f"prices/pages/{profile.code}")


SOURCES: dict[str, Factory] = {"http": _http, "saved": _saved}


def register_source(name: str, factory: Factory) -> None:
    SOURCES[name] = factory


def source_names() -> frozenset[str]:
    return frozenset(SOURCES)


class ChainFetcher:
    """Пробует источники по порядку. Отказ магазина (StoreBlocked) выводит источник из работы на
    остаток запуска, дальше страницы берёт следующий. Запрет robots.txt и лимит запросов не
    обходятся: они прекращают работу сразу."""

    def __init__(self, fetchers: list[tuple[str, Fetcher]]) -> None:
        self.fetchers = fetchers
        self.dead: dict[str, StoreBlocked] = {}

    def get(self, url: str) -> str:
        last: Exception | None = None
        for name, fetcher in self.fetchers:
            if name in self.dead:
                continue
            try:
                return fetcher.get(url)
            except StoreBlocked as e:
                self.dead[name] = e
                last = e
            except FetchFailed as e:
                last = e
        if last is None:  # живых источников не осталось
            raise next(iter(self.dead.values()))
        raise last


def build_fetcher(profile: StoreProfile, pages_dir: str | None = None) -> Fetcher:
    """`pages_dir` (флаг --pages-dir) заменяет цепочку чтением сохранённых страниц."""
    if pages_dir:
        return SavedPages(pages_dir)
    chain = [(name, SOURCES[name](profile)) for name in profile.sources]
    return chain[0][1] if len(chain) == 1 else ChainFetcher(chain)
