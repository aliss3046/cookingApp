"""Карточки товаров со страницы категории магазина.

Источники по порядку: данные страницы Nuxt (`__NUXT_DATA__`, формат devalue), Next.js
(`__NEXT_DATA__`), JSON-LD (`Product`, `ItemList`). Берётся первый, который дал товары. Карточки
в HTML-вёрстке без таких
данных (Дикси на Bitrix) пока не поддерживаются.

Разбирается только то, что сайт сам кладёт в страницу для её отображения. Внутренние интерфейсы
(`/api/`, `/ajax/`), запрещённые в robots.txt, не используются.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from prices.normalize import RawOffer

_NUXT: Final = re.compile(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)
_NEXT: Final = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_LD: Final = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
_WRAPPERS: Final = frozenset({"Reactive", "ShallowReactive", "Ref", "ShallowRef", "readonly"})
_EMPTY_REFS: Final = frozenset({"EmptyRef", "EmptyShallowRef"})
_OPAQUE: Final = frozenset({"Set", "Map", "Date", "null", "BigInt", "RegExp"})

STRATEGY_NUXT: Final = "nuxt"
STRATEGY_NEXT: Final = "next"
STRATEGY_JSON_LD: Final = "json-ld"


@dataclass(frozen=True)
class Listing:
    offers: tuple[RawOffer, ...]
    strategy: str | None
    skipped: int  # карточки без названия или цены


def hydrate_devalue(raw: list[Any]) -> Any:
    """Разворачивает массив devalue (так Nuxt 3 кладёт данные страницы): числа внутри — индексы."""
    memo: dict[int, Any] = {}

    def at(i: int) -> Any:
        if i in memo:
            return memo[i]
        if i < 0 or i >= len(raw):
            return None  # -1 = undefined и прочие служебные значения
        v = raw[i]
        if isinstance(v, list):
            if v and isinstance(v[0], str):
                if v[0] in _WRAPPERS:
                    memo[i] = out = at(v[1])
                    return out
                if v[0] in _EMPTY_REFS:
                    return None
                if v[0] in _OPAQUE:
                    return v
            memo[i] = out_list = []
            out_list.extend(at(x) if isinstance(x, int) else x for x in v)
            return out_list
        if isinstance(v, dict):
            memo[i] = out_dict = {}
            for k, x in v.items():
                out_dict[k] = at(x) if isinstance(x, int) else x
            return out_dict
        memo[i] = v
        return v

    return at(0)


def _walk(obj: Any) -> Iterator[dict[str, Any]]:
    """Обход в порядке документа (товары идут как на странице); общие узлы посещаются один раз."""
    stack = [obj]
    seen: set[int] = set()
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if id(cur) in seen:
                continue
            seen.add(id(cur))
            yield cur
            stack.extend(reversed(list(cur.values())))
        elif isinstance(cur, list):
            if id(cur) in seen:
                continue
            seen.add(id(cur))
            stack.extend(reversed(cur))


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ".").replace("\xa0", "").replace(" ", ""))
        except ValueError:
            return None
    return None


def _card_to_offer(d: dict[str, Any], store: str, category: str, now: datetime) -> RawOffer | None:
    """Карточка в формате «title/name + price». Нет названия или положительной цены: None."""
    title = d.get("title") or d.get("name")
    price = _number(d.get("price"))
    if not isinstance(title, str) or not title.strip() or price is None or price <= 0:
        return None
    ident = str(d.get("id") or d.get("sku") or d.get("link") or d.get("url") or title)

    unit = d.get("unit")
    label = unit if isinstance(unit, str) and unit and unit not in title else ""
    full_title = f"{title.strip()} {label}".strip()

    weighted = d.get("weighted")
    unit_price = _number(weighted.get("unitPrice")) if isinstance(weighted, dict) else None
    if isinstance(weighted, dict) and weighted.get("isWeighted") and unit_price:
        # цена на полке за порцию (700 г), цена за кг лежит отдельно в копейках
        return RawOffer(
            store=store, external_id=ident, title=full_title, price_text=f"{unit_price / 100:.2f}",
            fetched_at=now, price_unit="kg", category=category,
            in_stock=_in_stock(d),
        )  # fmt: skip
    return RawOffer(
        store=store, external_id=ident, title=full_title, price_text=f"{price:.2f}",
        fetched_at=now, category=category, in_stock=_in_stock(d),
    )  # fmt: skip


def _in_stock(d: dict[str, Any]) -> bool:
    q = d.get("quantity")
    return True if q is None or isinstance(q, bool) else (_number(q) or 0) > 0


def _from_json_state(
    root: Any, store: str, category: str, now: datetime
) -> tuple[list[RawOffer], int]:
    offers: dict[str, RawOffer] = {}
    skipped = 0
    for d in _walk(root):
        if not ("price" in d and ("title" in d or "name" in d)):
            continue
        offer = _card_to_offer(d, store, category, now)
        if offer is None:
            skipped += 1
        elif offer.external_id not in offers:
            offers[offer.external_id] = offer
    return list(offers.values()), skipped


def _json_ld_offers(
    blocks: list[str], store: str, category: str, now: datetime
) -> tuple[list[RawOffer], int]:
    offers: dict[str, RawOffer] = {}
    skipped = 0
    for block in blocks:
        try:
            root = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for d in _walk(root):
            types = d.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Product" not in types:
                continue
            offer_node = d.get("offers")
            offer_node = (
                offer_node[0] if isinstance(offer_node, list) and offer_node else offer_node
            )
            card = {
                "title": d.get("name"),
                "price": offer_node.get("price") if isinstance(offer_node, dict) else None,
                "id": d.get("sku") or d.get("url"),
            }
            offer = _card_to_offer(card, store, category, now)
            if offer is None:
                skipped += 1
            elif offer.external_id not in offers:
                offers[offer.external_id] = offer
    return list(offers.values()), skipped


def extract_offers(page: str, *, store: str, now: datetime, category: str = "") -> Listing:
    """Карточки товаров со страницы; пустой результат значит «такого формата тут нет»."""
    strategies: list[tuple[str, Callable[[], tuple[list[RawOffer], int]]]] = []
    if m := _NUXT.search(page):
        strategies.append(
            (STRATEGY_NUXT, lambda: _json_strategy(m[1], hydrate=True, args=(store, category, now)))
        )
    if m2 := _NEXT.search(page):
        strategies.append(
            (
                STRATEGY_NEXT,
                lambda: _json_strategy(m2[1], hydrate=False, args=(store, category, now)),
            )
        )
    blocks = _LD.findall(page)
    if blocks:
        strategies.append((STRATEGY_JSON_LD, lambda: _json_ld_offers(blocks, store, category, now)))

    total_skipped = 0
    for name, run in strategies:
        offers, skipped = run()
        total_skipped += skipped
        if offers:
            return Listing(tuple(offers), name, total_skipped)
    return Listing((), None, total_skipped)


def _json_strategy(
    text: str, *, hydrate: bool, args: tuple[str, str, datetime]
) -> tuple[list[RawOffer], int]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [], 0
    root = hydrate_devalue(data) if hydrate and isinstance(data, list) else data
    return _from_json_state(root, *args)


def extract_categories(page: str) -> list[tuple[int, str, str]]:
    """Дерево категорий страницы: (глубина, код, название), чтобы выбрать адреса для профиля."""
    m = _NUXT.search(page)
    if not m:
        return []
    try:
        data = json.loads(m[1])
    except json.JSONDecodeError:
        return []
    root = hydrate_devalue(data) if isinstance(data, list) else data
    out: list[tuple[int, str, str]] = []
    seen: set[str] = set()

    def visit(node: Any, depth: int) -> None:
        if isinstance(node, dict):
            code, name = node.get("code"), node.get("name")
            if isinstance(code, str) and isinstance(name, str) and "children" in node:
                if code not in seen:
                    seen.add(code)
                    out.append((depth, code, name))
                for child in node["children"] or []:
                    visit(child, depth + 1)
                return
            for v in node.values():
                visit(v, depth)
        elif isinstance(node, list):
            for v in node:
                visit(v, depth)

    visit(root, 0)
    return out
