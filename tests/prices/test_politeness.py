from datetime import date

import pytest

from prices.politeness import (
    BLOCK_PAGE_MAX_CHARS,
    MAX_DAILY_LIMIT,
    MIN_DELAY_FLOOR_S,
    BudgetExceeded,
    DailyBudget,
    RateLimiter,
    looks_blocked,
)


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def limiter(delay, t):
    return RateLimiter(delay, clock=t.clock, sleep=t.sleep)


def test_first_request_does_not_wait_and_second_waits_the_rest():
    t = FakeTime()
    rl = limiter(20, t)
    assert rl.wait("a.test") == 0
    t.now += 5
    assert rl.wait("a.test") == pytest.approx(15)
    assert t.slept == [pytest.approx(15)]
    t.now += 100  # давно: ждать нечего
    assert rl.wait("a.test") == 0


def test_hosts_are_independent():
    t = FakeTime()
    rl = limiter(20, t)
    rl.wait("a.test")
    assert rl.wait("b.test") == 0


def test_delay_has_a_floor_and_robots_delay_can_raise_it():
    t = FakeTime()
    rl = limiter(1, t)  # просили 1 секунду, пол 20
    assert rl.min_delay_s == MIN_DELAY_FLOOR_S
    rl.wait("a.test")
    assert rl.wait("a.test", extra_delay_s=45) == pytest.approx(45)


def test_daily_budget_counts_and_resets_next_day():
    day = {"d": date(2026, 10, 13)}
    b = DailyBudget(2, today=lambda: day["d"])
    b.take()
    b.take()
    with pytest.raises(BudgetExceeded):
        b.take()
    day["d"] = date(2026, 10, 14)
    b.take()
    assert b.used == 1


@pytest.mark.parametrize("limit", [0, -1, MAX_DAILY_LIMIT + 1])
def test_daily_budget_rejects_bad_limits(limit):
    with pytest.raises(ValueError, match="лимит"):
        DailyBudget(limit)


@pytest.mark.parametrize(
    "body",
    [
        "Проблемы со связью. Проверьте настройки интернета и VPN",
        "<h1>403 Error</h1> Access to lenta.com is forbidden.",
        "Access Denied",
        "Подтвердите, что вы не робот (captcha)",
        "Доступ ограничен",
    ],
)
def test_block_pages_are_recognised(body):
    assert looks_blocked(body)


def test_big_real_pages_and_normal_text_are_not_blocked():
    assert looks_blocked("Молоко 1 л — 89 ₽") is None
    big = "captcha " + "x" * BLOCK_PAGE_MAX_CHARS  # настоящая страница может упоминать слово
    assert looks_blocked(big) is None
