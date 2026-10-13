"""Вежливость к чужим сайтам: пауза, суточный лимит, распознавание блокировки.

Принципы (docs/stores.md): один запрос за раз, не чаще раза в `min_delay_s` на сайт, суточный
потолок запросов, остановка при блокировке (401/403/429 или страница-заглушка), а не обход.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date

# Не меньше: у Дикси в robots.txt для роботов Yandex указано 20 секунд, берём как разумный минимум.
MIN_DELAY_FLOOR_S = 20.0
MAX_DAILY_LIMIT = 500

# Заглушки вместо страницы: короткий ответ 200 с таким текстом считается блокировкой.
BLOCK_MARKERS = (
    "проблемы со связью",
    "проверьте настройки интернета и vpn",
    "access to",  # «Access to lenta.com is forbidden»
    "is forbidden",
    "access denied",
    "captcha",
    "капча",
    "подтвердите, что вы не робот",
    "are you a robot",
    "доступ ограничен",
)
BLOCK_PAGE_MAX_CHARS = 20_000


class FetchRefused(Exception):
    """Базовая ошибка: запрос не выполнен по причине вежливости, а не сбоя сети."""


class NotAllowed(FetchRefused):
    """robots.txt запрещает адрес (или его не удалось прочитать)."""


class BudgetExceeded(FetchRefused):
    """Исчерпан суточный лимит запросов к сайту."""


class StoreBlocked(FetchRefused):
    """Сайт блокирует клиента (401/403/429 или страница-заглушка). Останавливаемся, не обходим."""

    def __init__(self, reason: str, status: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.status = status


def looks_blocked(body: str) -> str | None:
    """Причина, если ответ похож на заглушку блокировки; иначе None.

    Настоящие страницы большие, заглушки короткие: длинные ответы не проверяются.
    """
    if len(body) > BLOCK_PAGE_MAX_CHARS:
        return None
    low = body.lower()
    for marker in BLOCK_MARKERS:
        if marker in low:
            return f"страница-заглушка («{marker}»)"
    return None


class RateLimiter:
    """Не чаще одного запроса в `min_delay_s` на сайт."""

    def __init__(
        self,
        min_delay_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.min_delay_s = max(min_delay_s, MIN_DELAY_FLOOR_S)
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def wait(self, host: str, extra_delay_s: float = 0.0) -> float:
        """Ждёт, пока можно идти на `host`. Возвращает, сколько секунд прождали."""
        delay = max(self.min_delay_s, extra_delay_s)
        last = self._last.get(host)
        waited = 0.0
        if last is not None:
            waited = max(0.0, delay - (self._clock() - last))
            if waited:
                self._sleep(waited)
        self._last[host] = self._clock()
        return waited


class DailyBudget:
    """Суточный потолок запросов. Сбрасывается со сменой даты."""

    def __init__(self, limit: int, *, today: Callable[[], date] = date.today):
        if not 1 <= limit <= MAX_DAILY_LIMIT:
            raise ValueError(
                f"суточный лимит должен быть от 1 до {MAX_DAILY_LIMIT}, получено {limit}"
            )
        self.limit = limit
        self._today = today
        self._day = today()
        self.used = 0

    def take(self) -> None:
        if self._today() != self._day:
            self._day, self.used = self._today(), 0
        if self.used >= self.limit:
            raise BudgetExceeded(f"суточный лимит {self.limit} запросов исчерпан")
        self.used += 1
