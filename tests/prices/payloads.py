"""Помощники тестов: данные страницы в формате Nuxt (devalue) и готовые карточки.

Структура карточки повторяет увиденную на странице каталога Магнита 13.10.2026 (поля title, price,
unit, weighted.unitPrice в копейках за кг, quantity). Сами страницы в репозиторий не сохраняются.
"""

from __future__ import annotations

import json
from typing import Any


def devalue(root: Any) -> list[Any]:
    """Плоский массив devalue: словари и списки хранят индексы, корень под индексом 0."""
    arr: list[Any] = []

    def add(v: Any) -> int:
        idx = len(arr)
        arr.append(None)
        if isinstance(v, dict):
            arr[idx] = {k: add(x) for k, x in v.items()}
        elif isinstance(v, list):
            arr[idx] = [add(x) for x in v]
        else:
            arr[idx] = v
        return idx

    add(root)
    return arr


def nuxt_page(root: Any) -> str:
    data = json.dumps(devalue(root), ensure_ascii=False)
    return (
        "<html><head><title>Каталог</title></head><body>"
        f'<script type="application/json" id="__NUXT_DATA__" data-ssr="true">{data}</script>'
        "</body></html>"
    )


def card(
    ident: str,
    title: str,
    price: str | float,
    *,
    unit: str | None = None,
    unit_price: int | None = None,
    quantity: int | None = 10,
) -> dict[str, Any]:
    weighted = {"isWeighted": unit_price is not None, "unitPrice": unit_price, "step": None}
    return {
        "id": ident,
        "title": title,
        "link": f"/product/{ident}-slug?shopCode=992301&shopType=dostavka",
        "price": price,
        "oldPrice": "",
        "unit": unit,
        "weighted": weighted,
        "quantity": quantity,
    }


def page_with(cards: list[dict[str, Any]]) -> str:
    return nuxt_page({"data": {"goods-search:abc": {"goods": cards, "pagination": {"page": 1}}}})
