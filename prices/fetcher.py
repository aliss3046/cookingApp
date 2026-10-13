"""Вежливый загрузчик страниц магазинов.

Перед каждым запросом: robots.txt (с шаблонами, нечитаемый запрещает всё), суточный лимит, пауза.
После: блокировка (401/403/429 или страница-заглушка) останавливает работу с магазином. Ничего не
обходится: User-Agent честный, прокси нет, повторов на отказы нет.
"""

from __future__ import annotations

import time
import urllib.error
from collections.abc import Callable
from urllib.parse import urlsplit

from importers.errors import FetchFailed
from importers.recipe_page import (
    USER_AGENT,
    Opener,
    _default_opener,
    fetch_html,
    fetch_robots,
)
from importers.robots import Robots
from prices.politeness import (
    DailyBudget,
    NotAllowed,
    RateLimiter,
    StoreBlocked,
    looks_blocked,
)

BLOCK_STATUSES = frozenset({401, 403, 429})


class PoliteFetcher:
    def __init__(
        self,
        *,
        min_delay_s: float = 20.0,
        daily_limit: int = 200,
        opener: Opener = _default_opener,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        user_agent: str = USER_AGENT,
    ):
        self._opener = opener
        self._sleep = sleep
        self._ua = user_agent
        self._limiter = RateLimiter(min_delay_s, clock=clock, sleep=sleep)
        self._budget = DailyBudget(daily_limit)
        self._robots: dict[str, Robots] = {}

    @property
    def requests_made(self) -> int:
        return self._budget.used

    def _robots_for(self, url: str) -> Robots:
        host = urlsplit(url).netloc
        cached = self._robots.get(host)
        if cached is not None:
            return cached
        self._budget.take()
        self._limiter.wait(host)
        try:
            robots = fetch_robots(url, opener=self._opener, sleep=self._sleep)
        except FetchFailed as e:
            _raise_if_blocked(e)
            raise
        self._robots[host] = robots
        return robots

    def get(self, url: str) -> str:
        """Страница или исключение: NotAllowed, BudgetExceeded, StoreBlocked, FetchFailed."""
        robots = self._robots_for(url)
        if robots.unreadable:  # 401/403 на robots.txt: сайт не пускает автоматических клиентов
            raise StoreBlocked("robots.txt недоступен (401/403)")
        if not robots.allowed(self._ua, url):
            raise NotAllowed(f"robots.txt запрещает: {url}")
        self._budget.take()
        self._limiter.wait(urlsplit(url).netloc, robots.crawl_delay(self._ua) or 0.0)
        try:
            body = fetch_html(url, opener=self._opener, robots=lambda _u: True, sleep=self._sleep)
        except FetchFailed as e:
            _raise_if_blocked(e)
            raise
        if reason := looks_blocked(body):
            raise StoreBlocked(reason)
        return body


def _raise_if_blocked(error: FetchFailed) -> None:
    cause = error.__cause__
    if isinstance(cause, urllib.error.HTTPError) and cause.code in BLOCK_STATUSES:
        raise StoreBlocked(f"HTTP {cause.code}", status=cause.code) from error
