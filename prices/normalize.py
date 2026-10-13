"""Нормализация данных карточки товара: цена, фасовка, цена за кг, способ продажи, марка.

Разбирает строки, как их отдаёт парсер магазина («129 99 ₽», «Молоко 3,2%, 930 мл»),
в единый формат для таблиц `products` и `prices` (docs/schema.md). Сети здесь нет:
провайдеры Дикси и Ленты подают сюда уже извлечённый текст, поэтому всё тестируется
на строках. Деньги — Decimal, чтобы не терять копейки.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Final, Literal

SaleMode = Literal["pack_mass", "pack_count", "per_piece", "by_weight", "unknown"]
PriceUnit = Literal["pack", "kg", "piece"]

_CENT: Final = Decimal("0.01")
_SPACES: Final = re.compile(r"[\s   ]+")
_CURRENCY: Final = re.compile(r"₽|\bруб(?:лей|ля|ль)?\.?|\bр\.|\brub\b|\bот\b", re.I)


class PriceParseError(ValueError):
    pass


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


# --- цена ---

# «1 299» — тысячи через пробел; «129 99» — рубли и копейки отдельно (Дикси);
# «129,99» и «129.99» — десятичная запятая или точка; «1 299 90» — всё вместе.
_PRICE_RE: Final = re.compile(
    r"(?P<rub>\d{1,3}(?: \d{3})+|\d+)(?:[.,](?P<dec>\d{1,2})| (?P<kop>\d{2}))?"
)


def parse_price(text: str) -> Decimal:
    """Цена из текста карточки. Пустая или нечитаемая строка — PriceParseError."""
    s = _CURRENCY.sub(" ", text or "")
    s = _SPACES.sub(" ", s).strip()
    m = _PRICE_RE.fullmatch(s)
    if not m:
        raise PriceParseError(f"не похоже на цену: {text!r}")
    rub = int(m["rub"].replace(" ", ""))
    cents = m["dec"] or m["kop"] or "0"
    if len(cents) == 1:
        cents += "0"
    value = Decimal(rub) + Decimal(int(cents)) / 100
    if value <= 0:
        raise PriceParseError(f"цена должна быть больше нуля: {text!r}")
    return _money(value)


# --- фасовка ---


@dataclass(frozen=True)
class Pack:
    qty: float  # всего в упаковке: г, мл или штук
    unit: str  # g | ml | pcs
    count: int = 1  # штук в упаковке («2 x 100 г», «10 шт»)
    approx: bool = False  # «~1 кг» у весовых товаров


_PACK_UNITS: Final = {
    "г": ("g", 1),
    "гр": ("g", 1),
    "кг": ("g", 1000),
    "мл": ("ml", 1),
    "л": ("ml", 1000),
    "шт": ("pcs", 1),
}
_NUM: Final = r"\d+(?:[.,]\d+)?"
_UNIT: Final = r"(?P<unit>кг|гр|г|мл|л|шт)\.?(?![а-яё])"
_PACK_RE: Final = re.compile(
    rf"(?P<approx>[~≈]\s*)?(?:(?P<count>\d+)\s*[xх×*]\s*)?(?P<qty>{_NUM})\s*{_UNIT}", re.I
)


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def parse_pack(title: str) -> Pack | None:
    """Фасовка из названия. Берётся последнее упоминание: размер обычно в конце названия."""
    s = _SPACES.sub(" ", title or "").lower()
    found = None
    for m in _PACK_RE.finditer(s):
        found = m
    if found is None:
        return None
    unit, factor = _PACK_UNITS[found["unit"].lower()]
    each = _num(found["qty"]) * factor
    count = int(found["count"]) if found["count"] else 1
    if count < 1 or each <= 0:
        return None
    if unit == "pcs":
        return Pack(qty=each * count, unit="pcs", count=int(each * count))
    return Pack(qty=each * count, unit=unit, count=count, approx=bool(found["approx"]))


# --- цена за килограмм ---

_PER_KG_RE: Final = re.compile(r"(?:за|/)\s*(?:1\s*)?(?:кг|л)\b\.?", re.I)
_PER_100_RE: Final = re.compile(r"(?:за|/)\s*100\s*(?:г|гр|мл)\b\.?", re.I)


def parse_price_per_kg(text: str) -> Decimal | None:
    """«199,90 ₽/кг», «Цена за 1 кг: 199,90 ₽», «за 100 г 19,99 ₽» -> цена за кг.

    Цена за литр считается ценой за кг (г и мл в модели равны). Без указания
    единицы — None: «цена за 1 шт» за кг не выдаётся.
    """
    if not text:
        return None
    multiplier = Decimal(1)
    m = _PER_KG_RE.search(text)
    if not m:
        m = _PER_100_RE.search(text)
        multiplier = Decimal(10)
    if not m:
        return None
    rest = f"{text[: m.start()]} {text[m.end() :]}"
    rest = re.sub(r"\bцена\b|:", " ", rest, flags=re.I)
    return _money(parse_price(rest) * multiplier)


# --- способ продажи и марка ---

_WEIGHT_WORDS: Final = re.compile(r"весов|на\s+вес|развес", re.I)


def detect_sale_mode(title: str, pack: Pack | None, price_unit: PriceUnit) -> SaleMode:
    """Как продаётся товар (см. domain.SaleMode в Go).

    `price_unit` — за что указана основная цена карточки: упаковку, кг или штуку.
    """
    if price_unit == "kg" or _WEIGHT_WORDS.search(title or ""):
        return "by_weight"
    if price_unit == "piece":
        return "per_piece"
    if pack is None:
        return "unknown"
    if pack.unit == "pcs":
        return "pack_count" if pack.count > 1 else "per_piece"
    return "pack_mass"


_QUOTED: Final = re.compile(r"[«\"“„]([^»\"”“]{2,40})[»\"”“]")


def extract_brand(title: str, known_brands: Iterable[str] = ()) -> str:
    """Марка: текст в кавычках («Простоквашино») или самая длинная известная марка.

    Пусто — марка не определена; такие товары в корзине идут как отдельная «марка».
    """
    if m := _QUOTED.search(title or ""):
        return m[1].strip()
    lower = (title or "").lower().replace("ё", "е")
    best = ""
    for brand in known_brands:
        b = brand.lower().replace("ё", "е")
        if (
            b
            and re.search(rf"(?<![а-яa-z]){re.escape(b)}(?![а-яa-z])", lower)
            and len(brand) > len(best)
        ):
            best = brand
    return best


# --- карточка целиком ---


@dataclass(frozen=True)
class RawOffer:
    """Текст карточки, как его извлёк провайдер магазина."""

    store: str  # dixy | lenta | manual
    external_id: str
    title: str
    price_text: str
    fetched_at: datetime
    price_unit: PriceUnit = "pack"
    card_price_text: str | None = None
    unit_price_text: str | None = None  # «199,90 ₽/кг»
    in_stock: bool = True
    store_only: bool = False
    brand_hint: str | None = None
    category: str = ""


@dataclass(frozen=True)
class NormalizedOffer:
    """Строки для `products` и `prices`."""

    store: str
    external_id: str
    title: str
    brand: str
    sale_mode: SaleMode
    pack_qty: float | None
    pack_unit: str | None
    price: Decimal
    card_price: Decimal | None
    price_per_kg: Decimal | None
    in_stock: bool
    store_only: bool
    fetched_at: datetime
    category: str = ""
    source: str = "site"
    notes: tuple[str, ...] = field(default=())


def normalize_offer(raw: RawOffer, known_brands: Iterable[str] = ()) -> NormalizedOffer:
    """Нормализует карточку. Нечитаемая основная цена — PriceParseError (товар пропускается,
    воркер считает такие случаи для алерта о смене вёрстки)."""
    notes: list[str] = []
    price = parse_price(raw.price_text)

    card_price = None
    if raw.card_price_text:
        try:
            card_price = parse_price(raw.card_price_text)
        except PriceParseError:
            notes.append("card_price_unreadable")

    pack = parse_pack(raw.title)
    mode = detect_sale_mode(raw.title, pack, raw.price_unit)

    per_kg = parse_price_per_kg(raw.unit_price_text or "")
    if per_kg is None and mode == "by_weight":
        per_kg = price  # основная цена весового товара — уже за кг
    if per_kg is None and mode == "pack_mass" and pack is not None:
        per_kg = _money(price / Decimal(str(pack.qty)) * 1000)
        notes.append("price_per_kg_derived")
    if mode == "unknown":
        notes.append("sale_mode_unknown")

    pack_qty = pack.count if mode == "pack_count" and pack else pack.qty if pack else None
    return NormalizedOffer(
        store=raw.store,
        external_id=raw.external_id,
        title=_SPACES.sub(" ", raw.title).strip(),
        brand=(raw.brand_hint or "").strip() or extract_brand(raw.title, known_brands),
        sale_mode=mode,
        pack_qty=None if mode in ("by_weight", "per_piece") else pack_qty,
        pack_unit=None if mode in ("by_weight", "per_piece") or pack is None else pack.unit,
        price=price,
        card_price=card_price,
        price_per_kg=per_kg,
        in_stock=raw.in_stock,
        store_only=raw.store_only,
        fetched_at=raw.fetched_at,
        category=raw.category,
        notes=tuple(notes),
    )
