"""robots.txt по RFC 9309. Правила взяты из реальных файлов магазинов, прочитанных 13.10.2026."""

import pytest

from importers.robots import UNREADABLE, Robots, parse_robots

UA = "cookingApp-recipe-import/0.1 (+https://github.com/aliss3046/cookingApp)"

# Урезанный robots.txt Магнита: шаблоны, которых не понимает urllib.robotparser.
MAGNIT = """
User-agent: *
Allow: *.js
Allow: *.css
Disallow: /profile
Disallow: /*search
Disallow: *q=
Disallow: *pageNumber=
Disallow: *utm_
Disallow: /*?page=1$
Sitemap: https://magnit.ru/sitemap_index.xml
"""

DIXY = """
User-Agent: *
Allow: /bitrix/catalog_export/
Disallow: /search/
Disallow: *bitrix*
Disallow: *?arrFilter*
Disallow: /*sort=
Allow: /bitrix/*.js

User-Agent: Yandex
Disallow: /search/
Crawl-delay: 20
"""

PEREKRESTOK = """
User-agent: ClaudeBot
Disallow: /

User-agent: *
Disallow: /profile
Disallow: /*?q=
Disallow: /*search=*
Allow: /*cat/search*
"""


@pytest.fixture
def magnit():
    return parse_robots(MAGNIT)


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://magnit.ru/catalog", True),
        ("https://magnit.ru/catalog/molochnye", True),
        ("https://magnit.ru/profile/orders", False),  # префикс
        ("https://magnit.ru/search", False),  # /*search
        ("https://magnit.ru/catalog/search", False),
        ("https://magnit.ru/catalog?q=moloko", False),  # *q=
        ("https://magnit.ru/catalog?pageNumber=2", False),
        ("https://magnit.ru/catalog?utm_source=x", False),
        ("https://magnit.ru/catalog?page=1", False),  # /*?page=1$
        ("https://magnit.ru/catalog?page=2", True),  # $ — конец строки, page=2 не совпал
        ("https://magnit.ru/catalog?page=10", True),
        ("https://magnit.ru/static/app.js", True),
    ],
)
def test_magnit_wildcards(magnit, url, allowed):
    assert magnit.allowed(UA, url) is allowed


def test_stdlib_robotparser_would_miss_these_rules():
    # то, ради чего написан свой разбор: urllib.robotparser пропускает запрещённое
    import urllib.robotparser

    rp = urllib.robotparser.RobotFileParser()
    rp.parse(MAGNIT.splitlines())
    assert rp.can_fetch(UA, "https://magnit.ru/catalog?q=moloko") is True  # неверно
    assert parse_robots(MAGNIT).allowed(UA, "https://magnit.ru/catalog?q=moloko") is False


def test_longest_match_wins_and_allow_wins_a_tie():
    r = parse_robots(DIXY)
    assert r.allowed(UA, "https://dixy.ru/bitrix/catalog_export/yml.php")  # Allow длиннее *bitrix*
    assert not r.allowed(UA, "https://dixy.ru/bitrix/admin/")
    assert r.allowed(UA, "https://dixy.ru/bitrix/templates/x.js")  # Allow /bitrix/*.js длиннее
    assert not r.allowed(UA, "https://dixy.ru/catalog/milk/?arrFilter_1=2")
    assert not r.allowed(UA, "https://dixy.ru/catalog/milk/?sort=price")
    assert r.allowed(UA, "https://dixy.ru/catalog/milk/")
    tie = parse_robots("User-agent: *\nDisallow: /x\nAllow: /x\n")
    assert tie.allowed(UA, "https://a.test/x")


def test_crawl_delay_belongs_to_its_group():
    r = parse_robots(DIXY)
    assert r.crawl_delay(UA) is None  # 20 с указано для Yandex, не для нас
    assert r.crawl_delay("Yandex") == 20


def test_specific_agent_group_beats_star():
    r = parse_robots(PEREKRESTOK)
    assert r.allowed(UA, "https://p.test/cat/milk")
    assert not r.allowed("ClaudeBot/1.0", "https://p.test/cat/milk")
    assert not r.allowed(UA, "https://p.test/cat?q=moloko")
    assert not r.allowed(UA, "https://p.test/cat/x?search=moloko")
    assert r.allowed(UA, "https://p.test/cat/search")  # Allow /*cat/search* длиннее


def test_our_own_agent_token_is_matched():
    r = parse_robots(
        "User-agent: cookingApp-recipe-import\nDisallow: /\n\nUser-agent: *\nDisallow:\n"
    )
    assert not r.allowed(UA, "https://a.test/x")
    assert r.allowed("OtherBot/1", "https://a.test/x")


def test_empty_disallow_and_no_group_allow_everything():
    assert parse_robots("User-agent: *\nDisallow:\n").allowed(UA, "https://a.test/anything")
    assert parse_robots("").allowed(UA, "https://a.test/anything")
    assert parse_robots("User-agent: Other\nDisallow: /\n").allowed(UA, "https://a.test/x")


def test_unreadable_robots_forbids_everything():
    assert UNREADABLE.unreadable and not UNREADABLE.allowed(UA, "https://a.test/")
    assert not Robots(groups=(), unreadable=True).allowed(UA, "https://a.test/robots.txt")


def test_parsing_details():
    r = parse_robots(
        "# комментарий\n\nUser-agent: a\nUser-agent: *\nDisallow: /p # хвост\nCrawl-delay: abc\n"
        "Crawl-delay: 5\nSitemap: https://a.test/s.xml\nDisallow: /q$\nnonsense line\n"
    )
    assert r.sitemaps == ("https://a.test/s.xml",)
    assert r.crawl_delay(UA) == 5
    assert not r.allowed(UA, "https://a.test/p/x") and not r.allowed(UA, "https://a.test/q")
    assert r.allowed(UA, "https://a.test/q/x")  # $ — только точный конец
    assert r.allowed(UA, "https://a.test")  # пустой путь = «/»


def test_rules_before_any_user_agent_are_ignored():
    r = parse_robots("Disallow: /x\nCrawl-delay: 3\nUser-agent: *\nDisallow: /y\n")
    assert r.allowed(UA, "https://a.test/x") and not r.allowed(UA, "https://a.test/y")
    assert r.crawl_delay(UA) is None
