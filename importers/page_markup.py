"""Достаёт ингредиенты из HTML страницы рецепта. Сеть здесь не нужна.

Источники, в порядке надёжности:

1. JSON-LD (`schema.org/Recipe`, `recipeIngredient`).
2. Микроразметка (`itemprop="recipeIngredient"`): теги `<meta content>` или текст элемента.
3. Вёрстка: список, таблица или абзацы после надписи «Ингредиенты» / «Продукты» / «Состав».

Один источник часто врёт: в JSON-LD бывают только названия без количеств, а список после
надписи может оказаться меню сайта. Поэтому функция `extract_candidates` отдаёт ВСЕ
варианты по порядку, а выбирает лучший вызывающий код, который знает справочник
ингредиентов (`recipe_page.import_from_html`).
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Final

from importers.errors import NoRecipeFound

SOURCE_JSON_LD: Final = "json-ld"
SOURCE_MICRODATA: Final = "microdata"
SOURCE_HTML: Final = "html"

_HEADINGS: Final = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_CONTAINERS: Final = frozenset({"ul", "ol", "table"})
_SKIP_TAGS: Final = frozenset({"script", "style", "noscript", "template"})
_VOID_TAGS: Final = frozenset({"meta", "link", "br", "img", "input", "hr", "source", "wbr"})
# На границе этих тегов слова не должны слипаться: «200 г» + вложенный «просеять».
_BLOCK_TAGS: Final = frozenset(
    {
        "br",
        "p",
        "div",
        "li",
        "ul",
        "ol",
        "tr",
        "td",
        "th",
        "table",
        "section",
        "article",
        "dt",
        "dd",
    }
    | {"h1", "h2", "h3", "h4", "h5", "h6"}
)
_INGREDIENT_PROPS: Final = frozenset({"recipeingredient", "ingredients", "ingredient"})
_YIELD_PROP: Final = "recipeyield"

_LABEL_RE: Final = re.compile(
    r"(?:ингредиенты|продукты|состав|вам\s+понадобится)\b[^\n]{0,40}", re.I
)
_PORTIONS_RE: Final = re.compile(r"(\d{1,2})\s*(?:порц|персон|человек)", re.I)
_MAX_SECTIONS: Final = 8
_MAX_PARAGRAPHS: Final = 30
_PORTION_LOOKAHEAD: Final = 3  # текстовых узлов после надписи, где ищем «на 6 порций»


@dataclass(frozen=True)
class RecipeLD:
    title: str
    ingredients: tuple[str, ...]
    servings: object
    url: str | None = None
    source: str = SOURCE_JSON_LD


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("name") or value.get("text") or ""
    s = html.unescape(str(value))
    s = re.sub(r"<[^>]+>", " ", s)
    return _clean(s)


# --- JSON-LD ---


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


# --- микроразметка ---


class _MicrodataCollector(HTMLParser):
    """Собирает `itemprop="recipeIngredient"` (и `recipeYield`).

    Значение — `content` у `<meta>` либо текст элемента. Вложенные теги того же имени
    считаются, чтобы закрывающий тег не оборвал сбор раньше времени.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ingredients: list[str] = []
        self.yield_text: str | None = None
        self._skip = 0
        self._caps: list[dict[str, Any]] = []

    def _record(self, kind: str, text: str) -> None:
        if not (text := _clean(text)):
            return
        if kind == "ingredient":
            self.ingredients.append(text)
        elif self.yield_text is None:
            self.yield_text = text

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in _BLOCK_TAGS:
            self.handle_data(" ")
        for cap in self._caps:
            if cap["tag"] == tag:
                cap["depth"] += 1
        a = dict(attrs)
        props = (a.get("itemprop") or "").lower().split()
        kind = (
            "ingredient"
            if any(p in _INGREDIENT_PROPS for p in props)
            else "yield"
            if _YIELD_PROP in props
            else None
        )
        if kind is None:
            return
        if tag in _VOID_TAGS:
            self._record(kind, a.get("content") or "")
        else:
            self._caps.append({"tag": tag, "kind": kind, "depth": 0, "buf": []})

    def handle_data(self, data: str) -> None:
        if not self._skip:
            for cap in self._caps:
                cap["buf"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if tag in _BLOCK_TAGS:
            self.handle_data(" ")
        for i in range(len(self._caps) - 1, -1, -1):
            cap = self._caps[i]
            if cap["tag"] != tag:
                continue
            if cap["depth"] > 0:
                cap["depth"] -= 1
            else:
                self._record(cap["kind"], "".join(cap["buf"]))
                del self._caps[i]
            break


# --- вёрстка: список, таблица или абзацы после надписи ---


class _SectionCollector(HTMLParser):
    """Находит надпись «Ингредиенты»/«Продукты»/«Состав» и собирает то, что за ней.

    Кандидаты: каждый список или таблица верхнего уровня после надписи (строки таблицы
    склеиваются через « — ») и группа абзацев `<p>` вне списков. Вложенные списки
    (замены, пояснения) пропускаются. Сбор останавливается на следующем заголовке.
    Надпись может встречаться несколько раз (меню, потом сам рецепт): каждый раз
    начинается новый раздел. Заодно ищется число порций рядом с надписью.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[list[str]] = []
        self.paragraphs: list[list[str]] = []
        self.portions: int | None = None
        self.og_title = ""
        self.h1 = ""
        self.title = ""
        self._skip = 0
        self._open: list[str] = []
        self._label = False
        self._stop = False
        self._got = False
        self._cur: list[str] | None = None
        self._base = 0
        self._li: list[str] | None = None
        self._cells: list[str] | None = None
        self._cell: list[str] | None = None
        self._p: list[str] | None = None
        self._paras: list[str] = []
        self._portion_nodes = 0
        self._in_h1 = False
        self._in_title = False

    # -- служебное --

    def _flush_paras(self) -> None:
        if self._paras:
            self.paragraphs.append(self._paras)
        self._paras = []

    def _arm(self) -> None:
        """Началась новая надпись: предыдущий раздел закрыт."""
        self._flush_paras()
        self._label, self._stop, self._got = True, False, False
        self._portion_nodes = _PORTION_LOOKAHEAD

    def _collecting(self) -> bool:
        return self._label and not self._stop

    @property
    def page_title(self) -> str:
        return _clean(self.og_title or self.h1 or self.title)

    # -- события --

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in _BLOCK_TAGS:
            self._text_chunk(" ")
        if tag == "meta":
            a = dict(attrs)
            if a.get("property") == "og:title" and not self.og_title:
                self.og_title = _clean(a.get("content") or "")
        elif tag == "h1" and not self.h1:
            self._in_h1 = True
        elif tag == "title" and not self.title:
            self._in_title = True

        if (
            tag in _HEADINGS
            and self._collecting()
            and self._got
            and self._li is None
            and self._cell is None
        ):
            self._stop = True
            self._flush_paras()
        if tag in _CONTAINERS:
            self._open.append(tag)
            if self._collecting() and self._cur is None and len(self.sections) < _MAX_SECTIONS:
                self._flush_paras()  # абзацы закончились, начался список
                self._cur, self._base = [], len(self._open)
            return
        if self._cur is not None and len(self._open) == self._base:
            if tag == "li":
                self._li = []
            elif tag == "tr":
                self._cells = []
            elif tag in ("td", "th") and self._cells is not None:
                self._cell = []
        # не elif: абзац бывает и внутри страницы-обёртки в таблице, где идёт «сбор»
        if tag == "p" and self._collecting() and self._li is None and self._cell is None:
            self._p = []

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_h1:
            self.h1 += data
        if self._in_title:
            self.title += data
        text = data.strip()
        if not text:
            return
        if (not self._label or self._stop or self._got) and self._cur is None:
            if _LABEL_RE.fullmatch(text):
                self._arm()
                if m := _PORTIONS_RE.search(text):
                    self.portions = self.portions or int(m[1])
                if self._open:  # надпись внутри таблицы или списка: берём его
                    self._cur, self._base = [], len(self._open)
                return
        if self._portion_nodes > 0 and self.portions is None:
            if m := _PORTIONS_RE.search(text):
                self.portions = int(m[1])
            self._portion_nodes -= 1
        if self._stop:
            return
        self._text_chunk(data)

    def _text_chunk(self, data: str) -> None:
        """Кусок текста попадает в ячейку, пункт списка или абзац, если они сейчас собираются."""
        in_item = self._cur is not None and len(self._open) == self._base
        if in_item and self._cell is not None:
            self._cell.append(data)
        elif in_item and self._li is not None:
            self._li.append(data)
        elif self._p is not None:
            self._p.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "h1":
            self._in_h1 = False
        elif tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self._text_chunk(" ")

        if self._cur is not None and len(self._open) == self._base:
            if tag in ("td", "th") and self._cell is not None and self._cells is not None:
                if cell := _clean("".join(self._cell)):
                    self._cells.append(cell)
                self._cell = None
            elif tag == "tr" and self._cells is not None:
                if self._cells:
                    self._cur.append(" — ".join(self._cells))
                self._cells = None
            elif tag == "li" and self._li is not None:
                if item := _clean("".join(self._li)):
                    self._cur.append(item)
                self._li = None
        if tag in _CONTAINERS and self._open and self._open[-1] == tag:
            if self._cur is not None and len(self._open) == self._base:
                if self._cur:
                    self.sections.append(self._cur)
                    self._got = True
                self._cur = None
            self._open.pop()
        if tag == "p" and self._p is not None:
            if para := _clean("".join(self._p)):
                self._paras.append(para)
                self._got = True
                if len(self._paras) >= _MAX_PARAGRAPHS:
                    self._stop = True
                    self._flush_paras()
            self._p = None

    def close(self) -> None:
        super().close()
        self._flush_paras()


# --- сборка вариантов ---


def _digit_share(lines: tuple[str, ...]) -> float:
    return sum(1 for line in lines if re.search(r"\d", line)) / len(lines)


def extract_candidates(page: str) -> list[RecipeLD]:
    """Все варианты списка ингредиентов со страницы, по порядку надёжности.

    Название и число порций недостающим вариантам подставляются из других источников
    страницы (JSON-LD, микроразметка, надпись «на 6 порций»).
    """
    ld_collector = _LdJsonCollector()
    ld_collector.feed(page)
    ld_recipes: list[RecipeLD] = []
    name_hint = yield_hint = url_hint = None
    for block in ld_collector.blocks:
        for recipe in _walk(_loads(block)):
            name_hint = name_hint or _text(recipe.get("name")) or None
            yield_hint = yield_hint or recipe.get("recipeYield")
            url_hint = url_hint or _text(recipe.get("url")) or None
            raw = recipe.get("recipeIngredient") or recipe.get("ingredients") or []
            if isinstance(raw, str):
                raw = [raw]
            lines = tuple(t for t in (_text(x) for x in raw) if t)
            if lines:
                ld_recipes.append(
                    RecipeLD(
                        title=_text(recipe.get("name")) or "",
                        ingredients=lines,
                        servings=recipe.get("recipeYield"),
                        url=_text(recipe.get("url")) or None,
                    )
                )

    micro = _MicrodataCollector()
    micro.feed(page)
    sections = _SectionCollector()
    sections.feed(page)
    sections.close()

    title = name_hint or sections.page_title or "Без названия"
    servings = yield_hint or micro.yield_text or sections.portions

    out = [
        RecipeLD(
            title=r.title or title,
            ingredients=r.ingredients,
            servings=r.servings or servings,
            url=r.url or url_hint,
            source=SOURCE_JSON_LD,
        )
        for r in ld_recipes
    ]
    if micro.ingredients:
        out.append(RecipeLD(title, tuple(micro.ingredients), servings, url_hint, SOURCE_MICRODATA))
    for group in [*sections.sections, *sections.paragraphs]:
        out.append(RecipeLD(title, tuple(group), servings, url_hint, SOURCE_HTML))
    if not out:
        raise NoRecipeFound(
            "на странице нет ингредиентов: ни разметки schema.org/Recipe, ни списка после "
            "«Ингредиенты»"
        )
    return out


def extract_recipe(page: str) -> RecipeLD:
    """Лучший по количеству цифр вариант: первый, где у большинства строк есть число.

    Без справочника это грубая оценка; точный выбор делает `import_from_html`.
    """
    candidates = extract_candidates(page)
    for c in candidates:
        if _digit_share(c.ingredients) >= 0.5:
            return c
    return candidates[0]
