"""Импорт рецепта со страницы по разметке schema.org/Recipe (JSON-LD).

Сайт читается один раз по просьбе пары, с проверкой robots.txt, ограничением
размера и тайм-аутом. Сеть спрятана за функцией `fetch`, поэтому всё остальное
тестируется на сохранённых страницах.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from typing import Any, Final, Protocol
from urllib.parse import urljoin, urlsplit

from importers.directory import Directory
from importers.draft import RecipeDraft, build_draft

USER_AGENT: Final = "cookingApp-recipe-import/0.1 (+https://github.com/aliss3046/cookingApp)"
TIMEOUT_S: Final = 10
MAX_BYTES: Final = 3_000_000
WARNING_HTML_FALLBACK: Final = "html_fallback"


class RecipeImportError(Exception):
    """Базовая ошибка импорта рецепта."""


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
    source: str = "json-ld"  # json-ld | html (запасной разбор вёрстки)


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
    if value is None:
        return ""
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("name") or value.get("text") or ""
    s = html.unescape(str(value))
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_LABEL_RE: Final = re.compile(r"\s*ингредиенты\s*:?\s*", re.I)
_CONTAINERS: Final = frozenset({"ul", "ol", "table"})
_SKIP_TAGS: Final = frozenset({"script", "style", "noscript", "template"})


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class _IngredientListCollector(HTMLParser):
    """Запасной разбор для страниц без ингредиентов в JSON-LD.

    Ищет надпись «Ингредиенты» и берёт первый список (`ul`/`ol`) или таблицу после
    неё, либо ту, внутри которой надпись стоит (подпись таблицы). Строка таблицы
    склеивается через « — »: «Творог | 500 г» -> «Творог — 500 г».
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[str] = []
        self.og_title = ""
        self.h1 = ""
        self.title = ""
        self._skip = 0
        self._open: list[str] = []  # открытые списки и таблицы
        self._label = False
        self._container: str | None = None
        self._depth = 0
        self._done = False
        self._li: list[str] | None = None
        self._cells: list[str] | None = None
        self._cell: list[str] | None = None
        self._in_h1 = False
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if tag == "meta":
            a = dict(attrs)
            if a.get("property") == "og:title" and not self.og_title:
                self.og_title = _clean(a.get("content") or "")
        elif tag == "h1" and not self.h1:
            self._in_h1 = True
        elif tag == "title" and not self.title:
            self._in_title = True
        if tag in _CONTAINERS:
            self._open.append(tag)
        if self._done or not self._label:
            return
        if self._container is None:
            if tag in _CONTAINERS:
                self._container, self._depth = tag, 1
            return
        if tag == self._container:
            self._depth += 1
        elif tag == "li" and self._depth == 1:
            self._li = []
        elif tag == "tr":
            self._cells = []
        elif tag in ("td", "th") and self._cells is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_h1:
            self.h1 += data
        if self._in_title:
            self.title += data
        if self._done:
            return
        if not self._label:
            if _LABEL_RE.fullmatch(data):
                self._label = True
                if self._open:  # надпись внутри таблицы или списка: берём его
                    self._container, self._depth = self._open[-1], 1
            return
        if self._depth > 1:  # вложенные списки — пояснения и замены, не ингредиенты
            return
        if self._cell is not None:
            self._cell.append(data)
        elif self._li is not None:
            self._li.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if tag == "h1":
            self._in_h1 = False
        elif tag == "title":
            self._in_title = False
        if tag in _CONTAINERS and self._open and self._open[-1] == tag:
            self._open.pop()
        if self._done or self._container is None:
            return
        if tag in ("td", "th") and self._cell is not None and self._cells is not None:
            if text := _clean(" ".join(self._cell)):
                self._cells.append(text)
            self._cell = None
        elif tag == "tr" and self._cells is not None:
            if self._cells:
                self.items.append(" — ".join(self._cells))
            self._cells = None
        elif tag == "li" and self._li is not None and self._depth == 1:
            if text := _clean(" ".join(self._li)):
                self.items.append(text)
            self._li = None
        elif tag == self._container:
            self._depth -= 1
            if self._depth == 0:
                if self.items:
                    self._done = True
                else:  # пустой контейнер: ждём следующий
                    self._container = None

    @property
    def page_title(self) -> str:
        return _clean(self.og_title or self.h1 or self.title)


def extract_recipe(page: str) -> RecipeLD:
    """Рецепт со страницы: сначала JSON-LD, затем запасной разбор вёрстки.

    Если в JSON-LD есть Recipe без ингредиентов (так бывает), его название и число
    порций используются, а ингредиенты берутся из вёрстки.
    """
    collector = _LdJsonCollector()
    collector.feed(page)
    partial: dict[str, Any] | None = None
    for block in collector.blocks:
        for recipe in _walk(_loads(block)):
            raw = recipe.get("recipeIngredient") or recipe.get("ingredients") or []
            if isinstance(raw, str):
                raw = [raw]
            lines = tuple(t for t in (_text(x) for x in raw) if t)
            if not lines:
                partial = partial or recipe
                continue
            return RecipeLD(
                title=_text(recipe.get("name")) or "Без названия",
                ingredients=lines,
                servings=recipe.get("recipeYield"),
                url=_text(recipe.get("url")) or None,
            )

    fallback = _IngredientListCollector()
    fallback.feed(page)
    if fallback.items:
        partial = partial or {}
        return RecipeLD(
            title=_text(partial.get("name")) or fallback.page_title or "Без названия",
            ingredients=tuple(fallback.items),
            servings=partial.get("recipeYield"),
            url=_text(partial.get("url")) or None,
            source="html",
        )
    raise NoRecipeFound(
        "на странице нет ингредиентов: ни разметки schema.org/Recipe, ни списка после «Ингредиенты»"
    )


# --- загрузка страницы ---


class _Response(Protocol):
    headers: Any

    def read(self, n: int = -1) -> bytes: ...


Opener = Callable[[urllib.request.Request, float], _Response]
RobotsCheck = Callable[[str], bool]

RETRIES: Final = 1  # один повтор при сетевом сбое (на практике бывают обрывы TLS)
RETRY_DELAY_S: Final = 1.0


def _default_opener(req: urllib.request.Request, timeout: float) -> _Response:
    return urllib.request.urlopen(req, timeout=timeout)  # схема http(s) проверена в fetch_html


def _decode_body(body: bytes, encoding: str, max_bytes: int) -> bytes:
    """Распаковывает gzip/deflate: некоторые сайты сжимают ответ без запроса.
    Распакованный размер тоже ограничен (защита от «zip-бомбы»)."""
    enc = encoding.strip().lower()
    if enc in {"", "identity"}:
        return body
    if enc not in {"gzip", "x-gzip", "deflate"}:
        raise FetchFailed(f"неподдерживаемое сжатие ответа: {encoding}")
    wbits = 16 + zlib.MAX_WBITS if "gzip" in enc else zlib.MAX_WBITS
    d = zlib.decompressobj(wbits)
    try:
        out = d.decompress(body, max_bytes + 1)
    except zlib.error as e:
        raise FetchFailed(f"повреждённый сжатый ответ: {e}") from e
    if len(out) > max_bytes:
        raise PageTooLarge(f"страница больше {max_bytes} байт после распаковки")
    return out


def _get(
    url: str,
    *,
    opener: Opener,
    timeout: float,
    max_bytes: int,
    accept: str,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bytes, Any]:
    """GET с одним повтором при сетевом сбое. HTTP-ошибки (404 и т. п.) не повторяются."""
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "gzip"}
    )
    attempt = 0
    while True:
        try:
            resp = opener(req, timeout)
            body = resp.read(max_bytes + 1)
            break
        except urllib.error.HTTPError:
            raise
        except OSError as e:
            if attempt >= RETRIES:
                raise FetchFailed(f"не удалось загрузить {url}: {e}") from e
            attempt += 1
            sleep(RETRY_DELAY_S)
    if len(body) > max_bytes:
        raise PageTooLarge(f"страница больше {max_bytes} байт")
    headers = resp.headers or {}
    return _decode_body(body, headers.get("Content-Encoding", "") or "", max_bytes), headers


def _charset(headers: Any) -> str:
    m = re.search(r"charset=([\w-]+)", headers.get("Content-Type", "") or "", re.I)
    return m[1] if m else "utf-8"


def _decode_text(body: bytes, charset: str) -> str:
    try:
        return body.decode(charset, errors="replace")
    except LookupError:  # неизвестная кодировка в заголовке
        return body.decode("utf-8", errors="replace")


def robots_allows(
    url: str,
    *,
    opener: Opener = _default_opener,
    timeout: float = TIMEOUT_S,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Проверка robots.txt тем же загрузчиком, что и страница.

    Как в urllib.robotparser: 401/403 — запрещено всё, другие 4xx — разрешено всё.
    5xx и сетевой сбой — ошибка: молча идти на сайт, не зная правил, нельзя.
    """
    robots_url = urljoin(url, "/robots.txt")
    try:
        body, headers = _get(
            robots_url, opener=opener, timeout=timeout, max_bytes=500_000,
            accept="text/plain", sleep=sleep,
        )  # fmt: skip
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False
        if 400 <= e.code < 500:
            return True
        raise FetchFailed(f"robots.txt недоступен: HTTP {e.code}") from e
    except FetchFailed as e:
        raise FetchFailed(f"не удалось прочитать robots.txt: {e}") from e
    rp = urllib.robotparser.RobotFileParser(robots_url)
    rp.parse(_decode_text(body, _charset(headers)).splitlines())
    return rp.can_fetch(USER_AGENT, url)


def fetch_html(
    url: str,
    *,
    opener: Opener = _default_opener,
    robots: RobotsCheck | None = None,
    timeout: float = TIMEOUT_S,
    max_bytes: int = MAX_BYTES,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise BadUrl(f"нужна ссылка http(s): {url!r}")
    allowed = (
        robots(url)
        if robots is not None
        else robots_allows(url, opener=opener, timeout=timeout, sleep=sleep)
    )
    if not allowed:
        raise DisallowedByRobots(f"robots.txt запрещает загрузку {url}")
    try:
        body, headers = _get(
            url, opener=opener, timeout=timeout, max_bytes=max_bytes,
            accept="text/html", sleep=sleep,
        )  # fmt: skip
    except urllib.error.HTTPError as e:
        raise FetchFailed(f"не удалось загрузить {url}: HTTP {e.code}") from e
    return _decode_text(body, _charset(headers))


def import_from_html(page: str, directory: Directory, source_url: str | None = None) -> RecipeDraft:
    ld = extract_recipe(page)
    draft = build_draft(
        ld.title,
        list(ld.ingredients),
        directory,
        servings=ld.servings,
        source_url=source_url or ld.url,
    )
    if ld.source == "html":
        # список найден эвристикой по вёрстке: паре стоит проверить его целиком
        draft = replace(draft, warnings=(*draft.warnings, WARNING_HTML_FALLBACK))
    return draft


def import_recipe(
    url: str, directory: Directory, *, fetch: Callable[[str], str] = fetch_html
) -> RecipeDraft:
    """Импорт по ссылке: загрузка, разметка, черновик для проверки парой."""
    return import_from_html(fetch(url), directory, source_url=url)
