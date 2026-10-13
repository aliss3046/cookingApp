"""Импорт рецепта со страницы по разметке schema.org/Recipe (JSON-LD).

Сайт читается один раз по просьбе пары, с проверкой robots.txt, ограничением
размера и тайм-аутом. Сеть спрятана за функцией `fetch`, поэтому всё остальное
тестируется на сохранённых страницах.
"""

from __future__ import annotations

import html
import json
import re
import urllib.request
import urllib.robotparser
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Final, Protocol
from urllib.parse import urljoin, urlsplit

from importers.directory import Directory
from importers.draft import RecipeDraft, build_draft

USER_AGENT: Final = "cookingApp-recipe-import/0.1 (+https://github.com/aliss3046/cookingApp)"
TIMEOUT_S: Final = 10
MAX_BYTES: Final = 3_000_000


class RecipeImportError(Exception):
    """Базовая ошибка импорта (имя без конфликта со встроенным ImportError)."""


class BadUrl(RecipeImportError):
    pass


class DisallowedByRobots(RecipeImportError):
    pass


class PageTooLarge(RecipeImportError):
    pass


class FetchFailed(RecipeImportError):
    pass


class NoRecipeFound(RecipeImportError):
    pass


@dataclass(frozen=True)
class RecipeLD:
    title: str
    ingredients: tuple[str, ...]
    servings: object
    url: str | None = None


# --- разбор страницы ---


class _LdJsonCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._in_ld = False
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            kind = (dict(attrs).get("type") or "").split(";")[0].strip().lower()
            self._in_ld = kind == "application/ld+json"
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in_ld:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_ld:
            self.blocks.append("".join(self._buf))
            self._in_ld = False


def _loads(block: str) -> Any:
    text = block.strip()
    text = re.sub(r"^\s*<!\[CDATA\[|\]\]>\s*$", "", text)
    text = re.sub(r"^\s*<!--|-->\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # частая поломка: висячие запятые перед ] и }
        try:
            return json.loads(re.sub(r",\s*([\]}])", r"\1", text))
        except json.JSONDecodeError:
            return None


def _is_recipe(obj: dict[str, Any]) -> bool:
    t = obj.get("@type")
    types = t if isinstance(t, list) else [t]
    return any(isinstance(x, str) and x.lower() == "recipe" for x in types)


def _walk(obj: Any) -> Iterator[dict[str, Any]]:
    if isinstance(obj, list):
        for item in obj:
            yield from _walk(item)
    elif isinstance(obj, dict):
        if _is_recipe(obj):
            yield obj
        for key in ("@graph", "mainEntity", "mainEntityOfPage", "itemListElement", "item"):
            if key in obj:
                yield from _walk(obj[key])


def _text(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("name") or value.get("text") or ""
    s = html.unescape(str(value))
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_recipe(page: str) -> RecipeLD:
    """Первый рецепт со списком ингредиентов из JSON-LD страницы."""
    collector = _LdJsonCollector()
    collector.feed(page)
    for block in collector.blocks:
        for recipe in _walk(_loads(block)):
            raw = recipe.get("recipeIngredient") or recipe.get("ingredients") or []
            if isinstance(raw, str):
                raw = [raw]
            lines = tuple(t for t in (_text(x) for x in raw) if t)
            if not lines:
                continue
            return RecipeLD(
                title=_text(recipe.get("name")) or "Без названия",
                ingredients=lines,
                servings=recipe.get("recipeYield"),
                url=_text(recipe.get("url")) or None,
            )
    raise NoRecipeFound("на странице нет разметки schema.org/Recipe с ингредиентами")


# --- загрузка страницы ---


class _Response(Protocol):
    headers: Any

    def read(self, n: int = -1) -> bytes: ...


Opener = Callable[[urllib.request.Request, float], _Response]
RobotsCheck = Callable[[str], bool]


def _default_opener(req: urllib.request.Request, timeout: float) -> _Response:
    return urllib.request.urlopen(req, timeout=timeout)  # схема http(s) проверена в fetch_html


def robots_allows(url: str) -> bool:
    rp = urllib.robotparser.RobotFileParser(urljoin(url, "/robots.txt"))
    try:
        rp.read()
    except OSError as e:
        raise FetchFailed(f"не удалось прочитать robots.txt: {e}") from e
    return rp.can_fetch(USER_AGENT, url)


def fetch_html(
    url: str,
    *,
    opener: Opener = _default_opener,
    robots: RobotsCheck = robots_allows,
    timeout: float = TIMEOUT_S,
    max_bytes: int = MAX_BYTES,
) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise BadUrl(f"нужна ссылка http(s): {url!r}")
    if not robots(url):
        raise DisallowedByRobots(f"robots.txt запрещает загрузку {url}")

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        resp = opener(req, timeout)
        body = resp.read(max_bytes + 1)
    except OSError as e:
        raise FetchFailed(f"не удалось загрузить {url}: {e}") from e
    if len(body) > max_bytes:
        raise PageTooLarge(f"страница больше {max_bytes} байт")

    charset = None
    content_type = resp.headers.get("Content-Type", "") if resp.headers else ""
    if m := re.search(r"charset=([\w-]+)", content_type, re.I):
        charset = m[1]
    try:
        return body.decode(charset or "utf-8", errors="replace")
    except LookupError:  # неизвестная кодировка в заголовке
        return body.decode("utf-8", errors="replace")


def import_from_html(page: str, directory: Directory, source_url: str | None = None) -> RecipeDraft:
    ld = extract_recipe(page)
    return build_draft(
        ld.title,
        list(ld.ingredients),
        directory,
        servings=ld.servings,
        source_url=source_url or ld.url,
    )


def import_recipe(
    url: str, directory: Directory, *, fetch: Callable[[str], str] = fetch_html
) -> RecipeDraft:
    """Импорт по ссылке: загрузка, разметка, черновик для проверки парой."""
    return import_from_html(fetch(url), directory, source_url=url)
