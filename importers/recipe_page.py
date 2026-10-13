"""Импорт рецепта по ссылке: загрузка страницы и сборка черновика.

Сайт читается один раз по просьбе пары, с проверкой robots.txt, ограничением
размера и тайм-аутом. Сеть спрятана за функцией `fetch`, поэтому всё остальное
тестируется на сохранённых страницах. Разбор разметки: `importers.page_markup`.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
import zlib
from collections.abc import Callable
from dataclasses import replace
from typing import Any, Final, Protocol
from urllib.parse import urljoin, urlsplit

from importers.directory import Directory
from importers.draft import RecipeDraft, build_draft
from importers.errors import (
    BadUrl,
    DisallowedByRobots,
    FetchFailed,
    NoRecipeFound,
    PageTooLarge,
    RecipeImportError,
)
from importers.page_markup import (
    SOURCE_HTML,
    RecipeLD,
    extract_candidates,
    extract_recipe,
)

__all__ = [
    "BadUrl",
    "DisallowedByRobots",
    "FetchFailed",
    "NoRecipeFound",
    "PageTooLarge",
    "RecipeImportError",
    "RecipeLD",
    "extract_recipe",
    "fetch_html",
    "import_from_html",
    "import_recipe",
    "robots_allows",
]

USER_AGENT: Final = "cookingApp-recipe-import/0.1 (+https://github.com/aliss3046/cookingApp)"
TIMEOUT_S: Final = 10
MAX_BYTES: Final = 3_000_000
WARNING_HTML_FALLBACK: Final = "html_fallback"
WARNING_LOW_CONFIDENCE: Final = "low_confidence"
# вариант списка годится, если не меньше половины строк разобрано и сопоставлено без проверки
GOOD_SHARE: Final = 0.5


# --- загрузка страницы ---


class _Response(Protocol):
    headers: Any

    def read(self, n: int = -1) -> bytes: ...


Opener = Callable[[urllib.request.Request, float], _Response]
RobotsCheck = Callable[[str], bool]

RETRIES: Final = 2  # два повтора при сетевом сбое (на практике бывают обрывы TLS)
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
    """GET с повторами при сетевом сбое (пауза растёт: 1 с, 2 с).

    HTTP-ошибки (404 и т. п.) не повторяются.
    """
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
            sleep(RETRY_DELAY_S * attempt)
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


def _draft(ld: RecipeLD, directory: Directory, source_url: str | None) -> RecipeDraft:
    draft = build_draft(
        ld.title,
        list(ld.ingredients),
        directory,
        servings=ld.servings,
        source_url=source_url or ld.url,
    )
    if ld.source == SOURCE_HTML:
        # список найден эвристикой по вёрстке: паре стоит проверить его целиком
        draft = replace(draft, warnings=(*draft.warnings, WARNING_HTML_FALLBACK))
    return draft


def _share_ok(draft: RecipeDraft) -> float:
    return (len(draft.lines) - draft.review_count) / len(draft.lines) if draft.lines else 0.0


def import_from_html(page: str, directory: Directory, source_url: str | None = None) -> RecipeDraft:
    """Собирает черновик из лучшего варианта списка ингредиентов на странице.

    Варианты идут по надёжности (JSON-LD, микроразметка, вёрстка). Берётся первый, у
    которого не меньше половины строк разобрано и сопоставлено со справочником; иначе тот,
    у кого таких строк больше (с предупреждением `low_confidence`). Так JSON-LD без
    количеств или меню сайта вместо ингредиентов не попадают в черновик.
    """
    best: RecipeDraft | None = None
    best_share = -1.0
    for ld in extract_candidates(page):
        draft = _draft(ld, directory, source_url)
        share = _share_ok(draft)
        if share >= GOOD_SHARE:
            return draft
        if share > best_share:
            best, best_share = draft, share
    assert best is not None  # extract_candidates не возвращает пустой список
    return replace(best, warnings=(*best.warnings, WARNING_LOW_CONFIDENCE))


def import_recipe(
    url: str, directory: Directory, *, fetch: Callable[[str], str] = fetch_html
) -> RecipeDraft:
    """Импорт по ссылке: загрузка, разметка, черновик для проверки парой."""
    return import_from_html(fetch(url), directory, source_url=url)
