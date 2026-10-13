"""Импорт рецепта со страницы. Страницы — сохранённые фикстуры, сеть не используется."""

import gzip
import io
import ssl
import urllib.error
import zlib
from pathlib import Path

import pytest

from importers.directory import load_directory
from importers.recipe_page import (
    USER_AGENT,
    WARNING_HTML_FALLBACK,
    BadUrl,
    DisallowedByRobots,
    FetchFailed,
    NoRecipeFound,
    PageTooLarge,
    extract_recipe,
    fetch_html,
    import_from_html,
    import_recipe,
    robots_allows,
)

PAGES = Path(__file__).parent / "fixtures" / "pages"


def page(name: str) -> str:
    return (PAGES / name).read_text("utf-8")


@pytest.fixture(scope="module")
def directory():
    return load_directory()


def test_extract_from_graph():
    ld = extract_recipe(page("graph_recipe.html"))
    assert ld.title == "Борщ «классический»"
    assert ld.servings == ["4", "4 порции"]
    assert ld.url == "https://recipes.test/borsch"
    # html-сущности раскрыты, теги убраны
    assert "Картофель — 3 шт." in ld.ingredients
    assert "Томатная паста — 2 ст. л." in ld.ingredients
    assert len(ld.ingredients) == 6


def test_extract_type_list_old_field_and_trailing_commas():
    ld = extract_recipe(page("plain_recipe.html"))
    assert ld.title == "Сырники" and ld.servings == "6 порций" and len(ld.ingredients) == 4


def test_extract_nested_cdata_skips_broken_and_empty():
    ld = extract_recipe(page("nested_recipe.html"))
    assert ld.title == "Омлет" and ld.ingredients == ("Яйца — 3 шт.",) and ld.servings == 2


def test_no_recipe():
    with pytest.raises(NoRecipeFound):
        extract_recipe(page("no_recipe.html"))
    with pytest.raises(NoRecipeFound):
        extract_recipe("<html><body>просто текст</body></html>")


def test_import_from_html_builds_draft(directory):
    draft = import_from_html(page("graph_recipe.html"), directory)
    assert draft.title == "Борщ «классический»" and draft.default_servings == 4
    assert draft.source_url == "https://recipes.test/borsch"
    by_raw = {line.raw_text: line for line in draft.lines}
    garlic = by_raw["Чеснок — 3 зубчика"]
    assert (garlic.ingredient_id, garlic.qty_per_serving, garlic.unit) == ("garlic", 3.75, "g")
    beef = by_raw["Говядина на кости — 500 г"]
    assert (beef.ingredient_id, beef.qty_per_serving) == ("beef", 125)
    # «соль, перец — по вкусу» стало двумя необязательными строками
    assert [x.ingredient_id for x in draft.lines if x.optional] == ["salt", "black_pepper"]
    assert draft.review_count == 0


def test_import_recipe_uses_fetch_and_keeps_url(directory):
    seen = []

    def fake_fetch(url):
        seen.append(url)
        return page("plain_recipe.html")

    draft = import_recipe("https://recipes.test/syrniki", directory, fetch=fake_fetch)
    assert seen == ["https://recipes.test/syrniki"]
    assert draft.source_url == "https://recipes.test/syrniki" and draft.default_servings == 6


# --- загрузка страницы без сети ---


class FakeResponse:
    def __init__(self, body: bytes, headers: dict | None = None):
        self._body = io.BytesIO(body)
        self.headers = {"Content-Type": "text/html; charset=utf-8"} if headers is None else headers

    def read(self, n: int = -1) -> bytes:
        return self._body.read(n)


class FakeWeb:
    """Поддельный интернет: ответ или исключение по адресу; записывает запросы."""

    def __init__(self, routes: dict):
        self.routes = {k: list(v) if isinstance(v, list) else [v] for k, v in routes.items()}
        self.calls: list[tuple[str, str | None, str | None, float]] = []

    def __call__(self, req, timeout):
        self.calls.append(
            (req.full_url, req.get_header("User-agent"), req.get_header("Accept-encoding"), timeout)
        )
        queue = self.routes[req.full_url]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, BaseException):
            raise item
        return item


def http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "error", hdrs=None, fp=None)


PAGE = "https://x.test/r"
ROBOTS = "https://x.test/robots.txt"
ALLOW_ALL = FakeResponse(b"User-agent: *\nAllow: /\n", {"Content-Type": "text/plain"})


def allow(url):
    return True


def no_sleep(seconds):
    pass


def test_fetch_ok_checks_robots_with_same_opener():
    web = FakeWeb({ROBOTS: ALLOW_ALL, PAGE: FakeResponse("Привет".encode())})
    assert fetch_html(PAGE, opener=web, sleep=no_sleep) == "Привет"
    assert [c[0] for c in web.calls] == [ROBOTS, PAGE]
    assert all(c[1] == USER_AGENT and c[2] == "gzip" and c[3] == 10 for c in web.calls)


def test_fetch_decodes_declared_charset_and_survives_unknown_one():
    body = "Борщ".encode("cp1251")

    def page(content_type):
        web = FakeWeb({PAGE: FakeResponse(body, {"Content-Type": content_type})})
        return fetch_html(PAGE, opener=web, robots=allow)

    assert page("text/html; charset=windows-1251") == "Борщ"
    assert "Борщ" not in page("text/html; charset=nope")
    assert fetch_html(PAGE, opener=FakeWeb({PAGE: FakeResponse(b"ok", {})}), robots=allow) == "ok"


@pytest.mark.parametrize(
    "url", ["ftp://x.test/r", "file:///etc/passwd", "recipes.test/r", "https://"]
)
def test_fetch_rejects_bad_urls(url):
    with pytest.raises(BadUrl):
        fetch_html(url, opener=FakeWeb({}), robots=allow)


@pytest.mark.parametrize(
    "robots_txt",
    [b"User-agent: *\nDisallow: /\n", b"User-agent: cookingApp-recipe-import\nDisallow: /r\n"],
)
def test_fetch_respects_robots_txt(robots_txt):
    web = FakeWeb({ROBOTS: FakeResponse(robots_txt, {"Content-Type": "text/plain"})})
    with pytest.raises(DisallowedByRobots):
        fetch_html(PAGE, opener=web, sleep=no_sleep)
    assert [c[0] for c in web.calls] == [ROBOTS]  # страницу не трогали


def test_robots_gzip_is_unpacked():
    # Lifehacker отдаёт robots.txt в gzip, даже когда его не просят
    def web():  # новый ответ на каждый запрос: тело читается один раз
        body = gzip.compress(b"User-agent: *\nDisallow: /private/\n")
        return FakeWeb({ROBOTS: FakeResponse(body, {"Content-Encoding": "gzip"})})

    assert robots_allows("https://x.test/recipe/1", opener=web())
    assert not robots_allows("https://x.test/private/1", opener=web())


@pytest.mark.parametrize(
    ("code", "allowed"), [(404, True), (410, True), (401, False), (403, False)]
)
def test_robots_http_status(code, allowed):
    web = FakeWeb({ROBOTS: http_error(ROBOTS, code)})
    assert robots_allows(PAGE, opener=web, sleep=no_sleep) is allowed


def test_robots_server_error_and_network_failure():
    with pytest.raises(FetchFailed, match="HTTP 503"):
        robots_allows(PAGE, opener=FakeWeb({ROBOTS: http_error(ROBOTS, 503)}), sleep=no_sleep)
    with pytest.raises(FetchFailed, match="robots"):
        robots_allows(PAGE, opener=FakeWeb({ROBOTS: OSError("timeout")}), sleep=no_sleep)


def test_network_error_is_retried_once():
    sleeps = []
    web = FakeWeb({PAGE: [ssl.SSLError("UNEXPECTED_EOF"), FakeResponse(b"ok")]})
    assert fetch_html(PAGE, opener=web, robots=allow, sleep=sleeps.append) == "ok"
    assert len(web.calls) == 2 and sleeps == [1.0]


def test_network_error_twice_fails():
    web = FakeWeb({PAGE: OSError("connection refused")})
    with pytest.raises(FetchFailed, match="connection refused"):
        fetch_html(PAGE, opener=web, robots=allow, sleep=no_sleep)
    assert len(web.calls) == 2


def test_http_error_is_not_retried():
    web = FakeWeb({PAGE: http_error(PAGE, 404)})
    with pytest.raises(FetchFailed, match="HTTP 404"):
        fetch_html(PAGE, opener=web, robots=allow, sleep=no_sleep)
    assert len(web.calls) == 1


@pytest.mark.parametrize(
    ("encoding", "pack"),
    [
        ("gzip", gzip.compress),
        ("x-gzip", gzip.compress),
        ("deflate", zlib.compress),
        ("identity", bytes),
    ],
)
def test_compressed_page(encoding, pack):
    body = pack("<p>Борщ</p>".encode())
    web = FakeWeb({PAGE: FakeResponse(body, {"Content-Encoding": encoding})})
    assert fetch_html(PAGE, opener=web, robots=allow) == "<p>Борщ</p>"


def test_bad_compression():
    with pytest.raises(FetchFailed, match="сжатие"):
        fetch_html(
            PAGE,
            opener=FakeWeb({PAGE: FakeResponse(b"x", {"Content-Encoding": "br"})}),
            robots=allow,
        )
    with pytest.raises(FetchFailed, match="повреждённый"):
        fetch_html(
            PAGE,
            opener=FakeWeb({PAGE: FakeResponse(b"not gzip", {"Content-Encoding": "gzip"})}),
            robots=allow,
        )


def test_size_limits_before_and_after_unpacking():
    with pytest.raises(PageTooLarge):
        fetch_html(
            PAGE, opener=FakeWeb({PAGE: FakeResponse(b"x" * 11)}), robots=allow, max_bytes=10
        )
    assert fetch_html(
        PAGE, opener=FakeWeb({PAGE: FakeResponse(b"x" * 10)}), robots=allow, max_bytes=10
    )
    bomb = FakeResponse(gzip.compress(b"x" * 1000), {"Content-Encoding": "gzip"})
    with pytest.raises(PageTooLarge, match="распаковки"):
        fetch_html(PAGE, opener=FakeWeb({PAGE: bomb}), robots=allow, max_bytes=100)


def test_default_opener_calls_urlopen(monkeypatch):
    import importers.recipe_page as rp

    seen = []

    def fake_urlopen(req, timeout):
        seen.append((req.full_url, timeout))
        return FakeResponse(b"ok")

    monkeypatch.setattr(rp.urllib.request, "urlopen", fake_urlopen)
    assert rp.fetch_html(PAGE, robots=allow) == "ok"
    assert seen == [(PAGE, 10)]


def test_scalar_json_and_list_name():
    html_page = (
        '<script type="application/ld+json">"просто строка"</script>'
        '<script type="application/ld+json">{"@type": "Recipe", "name": ["Плов", "x"],'
        ' "recipeIngredient": ["Рис — 300 г"]}</script>'
        '<script type="application/ld+json">{"@type": "Recipe", "name": [],'
        ' "recipeIngredient": ["Рис — 300 г"]}</script>'
    )
    assert extract_recipe(html_page).title == "Плов"
    assert extract_recipe(html_page.split("</script>", 2)[2]).title == "Без названия"


def test_list_without_recipe_is_walked_to_the_end():
    html_page = (
        '<script type="application/ld+json">'
        '[{"@type": "Organization"}, {"@type": "WebSite"}]</script>'
    )
    with pytest.raises(NoRecipeFound):
        extract_recipe(html_page)


# --- запасной разбор вёрстки ---


def test_fallback_table_with_label_in_caption_uses_partial_json_ld():
    ld = extract_recipe(page("table_after_label.html"))
    assert ld.source == "html"
    assert ld.title == "Сырники с манкой" and ld.servings == "4 порции"
    assert ld.url == "https://recipes.test/syrniki-s-mankoj"
    # строка таблицы склеена через тире; пустая строка и вторая таблица не попали
    assert ld.ingredients == ("Творог — 500 г", "Яйца куриные — 1 шт.", "Крупа манная — 100 г")


def test_fallback_list_after_heading():
    ld = extract_recipe(page("list_after_heading.html"))
    assert ld.source == "html" and ld.servings is None and ld.url is None
    assert ld.title == "Оладьи на кефире"  # из h1 с вложенным тегом
    assert ld.ingredients == (
        "Кефир — 500 мл",
        "Мука — 2 стакана",
        "Яйцо — 1 шт.",  # вложенный подпункт с заменой отброшен
        "Соль — щепотка",
    )


@pytest.mark.parametrize(
    ("head", "want"),
    [
        ('<meta property="og:title" content=" Из og ">', "Из og"),
        ("<title>Из title</title>", "Из title"),
        ("", "Без названия"),
    ],
)
def test_fallback_title_sources(head, want):
    body = "<p>Ингредиенты</p><ol><li>Мука — 200 г</li></ol>"
    assert extract_recipe(f"<html><head>{head}</head><body>{body}</body></html>").title == want


def test_fallback_needs_a_list_after_the_label():
    with pytest.raises(NoRecipeFound):
        extract_recipe("<h2>Ингредиенты</h2><p>Мука — 200 г</p>")
    with pytest.raises(NoRecipeFound):
        extract_recipe("<script>Ингредиенты</script><ul><li>Мука — 200 г</li></ul>")


def test_import_from_html_marks_fallback(directory):
    draft = import_from_html(page("list_after_heading.html"), directory)
    assert WARNING_HTML_FALLBACK in draft.warnings and "servings_unknown" in draft.warnings
    assert [x.ingredient_id for x in draft.lines] == ["kefir", "wheat_flour", "egg", "salt"]
    json_ld = import_from_html(page("graph_recipe.html"), directory)
    assert WARNING_HTML_FALLBACK not in json_ld.warnings
