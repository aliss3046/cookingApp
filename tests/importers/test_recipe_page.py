"""Импорт рецепта со страницы. Страницы — сохранённые фикстуры, сеть не используется."""

import io
from pathlib import Path

import pytest

from importers.directory import load_directory
from importers.recipe_page import (
    USER_AGENT,
    BadUrl,
    DisallowedByRobots,
    FetchFailed,
    NoRecipeFound,
    PageTooLarge,
    extract_recipe,
    fetch_html,
    import_from_html,
    import_recipe,
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
    def __init__(self, body: bytes, content_type: str = "text/html; charset=utf-8"):
        self._body = io.BytesIO(body)
        self.headers = {"Content-Type": content_type}

    def read(self, n: int = -1) -> bytes:
        return self._body.read(n)


def opener_for(body: bytes, content_type: str = "text/html; charset=utf-8", calls=None):
    def opener(req, timeout):
        if calls is not None:
            calls.append((req.full_url, req.get_header("User-agent"), timeout))
        return FakeResponse(body, content_type)

    return opener


def allow(url):
    return True


def test_fetch_ok_sends_user_agent_and_timeout():
    calls = []
    text = fetch_html(
        "https://recipes.test/r", opener=opener_for("Привет".encode(), calls=calls), robots=allow
    )
    assert text == "Привет"
    assert calls == [("https://recipes.test/r", USER_AGENT, 10)]


def test_fetch_decodes_declared_charset_and_survives_unknown_one():
    body = "Борщ".encode("cp1251")
    assert (
        fetch_html(
            "https://x.test/",
            opener=opener_for(body, "text/html; charset=windows-1251"),
            robots=allow,
        )
        == "Борщ"
    )
    assert "Борщ" not in fetch_html(
        "https://x.test/", opener=opener_for(body, "text/html; charset=nope"), robots=allow
    )
    assert fetch_html("https://x.test/", opener=opener_for(b"ok", ""), robots=allow) == "ok"


@pytest.mark.parametrize(
    "url", ["ftp://x.test/r", "file:///etc/passwd", "recipes.test/r", "https://"]
)
def test_fetch_rejects_bad_urls(url):
    with pytest.raises(BadUrl):
        fetch_html(url, opener=opener_for(b""), robots=allow)


def test_fetch_respects_robots():
    with pytest.raises(DisallowedByRobots):
        fetch_html("https://x.test/r", opener=opener_for(b""), robots=lambda url: False)


def test_fetch_size_limit():
    with pytest.raises(PageTooLarge):
        fetch_html("https://x.test/r", opener=opener_for(b"x" * 11), robots=allow, max_bytes=10)
    assert fetch_html("https://x.test/r", opener=opener_for(b"x" * 10), robots=allow, max_bytes=10)


def test_fetch_network_error():
    def broken(req, timeout):
        raise OSError("connection refused")

    with pytest.raises(FetchFailed, match="connection refused"):
        fetch_html("https://x.test/r", opener=broken, robots=allow)


def test_robots_allows_reads_robots_txt(monkeypatch):
    import importers.recipe_page as rp

    class FakeParser:
        def __init__(self, url):
            self.url = url

        def read(self):
            pass

        def can_fetch(self, agent, url):
            return agent == USER_AGENT and "/private/" not in url

    monkeypatch.setattr(rp.urllib.robotparser, "RobotFileParser", FakeParser)
    assert rp.robots_allows("https://x.test/recipes/1")
    assert not rp.robots_allows("https://x.test/private/1")


def test_robots_unreachable(monkeypatch):
    import importers.recipe_page as rp

    class Broken:
        def __init__(self, url):
            pass

        def read(self):
            raise OSError("timeout")

    monkeypatch.setattr(rp.urllib.robotparser, "RobotFileParser", Broken)
    with pytest.raises(FetchFailed, match="robots"):
        rp.robots_allows("https://x.test/r")


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


def test_default_opener_calls_urlopen(monkeypatch):
    import importers.recipe_page as rp

    seen = []

    def fake_urlopen(req, timeout):
        seen.append((req.full_url, timeout))
        return FakeResponse(b"ok")

    monkeypatch.setattr(rp.urllib.request, "urlopen", fake_urlopen)
    assert rp.fetch_html("https://x.test/r", robots=allow) == "ok"
    assert seen == [("https://x.test/r", 10)]


def test_list_without_recipe_is_walked_to_the_end():
    html_page = (
        '<script type="application/ld+json">'
        '[{"@type": "Organization"}, {"@type": "WebSite"}]</script>'
    )
    with pytest.raises(NoRecipeFound):
        extract_recipe(html_page)
