import io
import urllib.error

import pytest

from importers.errors import FetchFailed
from importers.recipe_page import USER_AGENT
from prices.fetcher import PoliteFetcher
from prices.politeness import BudgetExceeded, NotAllowed, StoreBlocked

ROBOTS = "https://shop.test/robots.txt"
PAGE = "https://shop.test/catalog/milk"


class Response:
    def __init__(self, body: bytes, headers=None):
        self._b = io.BytesIO(body)
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}

    def read(self, n=-1):
        return self._b.read(n)


def http_error(url, code):
    return urllib.error.HTTPError(url, code, "x", hdrs=None, fp=None)


class Web:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, req, timeout):
        self.calls.append(req.full_url)
        item = self.routes[req.full_url]
        if isinstance(item, BaseException):
            raise item
        return Response(item) if isinstance(item, bytes) else item


class Clock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def fetcher(web, clock=None, **kw):
    clock = clock or Clock()
    return PoliteFetcher(opener=web, sleep=clock.sleep, clock=clock, **kw), clock


OK_ROBOTS = b"User-agent: *\nDisallow: /search\nDisallow: *q=\n"


def test_reads_robots_once_then_page_and_waits_between_requests():
    web = Web({ROBOTS: OK_ROBOTS, PAGE: b"<html>milk</html>"})
    f, clock = fetcher(web)
    assert f.get(PAGE) == "<html>milk</html>"
    assert web.calls == [ROBOTS, PAGE]
    assert clock.slept == [20.0]  # пауза между robots.txt и страницей
    assert f.requests_made == 2
    f.get(PAGE)  # robots.txt закеширован
    assert web.calls == [ROBOTS, PAGE, PAGE] and f.requests_made == 3


def test_robots_forbidden_url_is_not_fetched():
    web = Web({ROBOTS: OK_ROBOTS})
    f, _ = fetcher(web)
    for url in ("https://shop.test/search", "https://shop.test/catalog?q=milk"):
        with pytest.raises(NotAllowed, match=r"robots\.txt запрещает"):
            f.get(url)
    assert web.calls == [ROBOTS]  # страницы не трогали


def test_robots_crawl_delay_raises_the_pause():
    web = Web({ROBOTS: b"User-agent: *\nCrawl-delay: 45\n", PAGE: b"ok"})
    f, clock = fetcher(web)
    f.get(PAGE)
    assert clock.slept == [45.0]


def test_unreadable_robots_means_blocked_store():
    web = Web({ROBOTS: http_error(ROBOTS, 403)})
    f, _ = fetcher(web)
    with pytest.raises(StoreBlocked, match=r"robots\.txt недоступен"):
        f.get(PAGE)
    assert web.calls == [ROBOTS]


@pytest.mark.parametrize("code", [401, 403, 429])
def test_block_statuses_on_the_page_stop_the_store(code):
    web = Web({ROBOTS: OK_ROBOTS, PAGE: http_error(PAGE, code)})
    f, _ = fetcher(web)
    with pytest.raises(StoreBlocked) as e:
        f.get(PAGE)
    assert e.value.status == code and f"HTTP {code}" in e.value.reason
    assert web.calls.count(PAGE) == 1  # не повторяем и не обходим


def test_block_status_on_robots_request_stops_the_store():
    web = Web({ROBOTS: http_error(ROBOTS, 429)})
    f, _ = fetcher(web)
    with pytest.raises(StoreBlocked) as e:
        f.get(PAGE)
    assert e.value.status == 429


def test_block_page_with_status_200_is_recognised():
    body = "Проблемы со связью. Проверьте настройки интернета и VPN".encode()
    web = Web({ROBOTS: OK_ROBOTS, PAGE: body})
    f, _ = fetcher(web)
    with pytest.raises(StoreBlocked, match="заглушка"):
        f.get(PAGE)


def test_other_errors_are_not_blocks():
    web = Web({ROBOTS: OK_ROBOTS, PAGE: http_error(PAGE, 404)})
    f, _ = fetcher(web)
    with pytest.raises(FetchFailed, match="HTTP 404"):
        f.get(PAGE)
    web = Web({ROBOTS: http_error(ROBOTS, 503)})
    f, _ = fetcher(web)
    with pytest.raises(FetchFailed, match="HTTP 503"):
        f.get(PAGE)


def test_daily_budget_stops_requests():
    web = Web({ROBOTS: OK_ROBOTS, PAGE: b"ok"})
    f, _ = fetcher(web, daily_limit=2)  # robots.txt + одна страница
    f.get(PAGE)
    with pytest.raises(BudgetExceeded):
        f.get(PAGE)


def test_honest_user_agent_is_used():
    seen = []

    def opener(req, timeout):
        seen.append(req.get_header("User-agent"))
        return Response(OK_ROBOTS if req.full_url == ROBOTS else b"ok")

    f, _ = fetcher(opener)
    f.get(PAGE)
    assert set(seen) == {USER_AGENT}
