"""Разбор строки ингредиента: «2 ст. л. масла» -> название, количество, единица.

Правила без LLM. Всё, что разобрать не удалось, не теряется: строка помечается
`needs_review` с причиной и отдаётся фронтенду как есть (см. docs/cart-edge-cases.md).
LLM подключается позже только для строк, которые не прошли правила.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from importers.quantities import Quantity, find_quantities
from importers.units import match_unit, to_base

REASON_NO_NAME: Final = "no_name"
REASON_NO_QUANTITY: Final = "no_quantity"

_TO_TASTE: Final = re.compile(
    r"по\s+вкусу|по\s+желанию|для\s+(?:подачи|украшения|жарки|обжарки|смазывани\w*|смазки|посыпки"
    r"|присыпки|посыпания|фритюра|формы|противня|панировки)"
    r"|на\s+кончике\s+ножа|сколько\s+потребуется|немного"
)
_APPROX: Final = re.compile(r"\b(?:около|примерно|приблизительно|порядка)\b|~")
_HALF_UNIT: Final = re.compile(r"\bпол[- ]?(стакан\w*|литр\w*|ложк\w*|кило\w*)")
_PAREN: Final = re.compile(r"\(([^)]*)\)")
_EDGE_PUNCT: Final = " \t-–—:;,.·•*/\\"


@dataclass(frozen=True)
class ParsedLine:
    raw: str
    name: str
    qty: float | None  # в базовых единицах; для диапазона верхняя граница
    unit: str | None  # g | ml | pcs
    source_unit: str | None  # единица из строки: tbsp, clove, pcs ...
    optional: bool = False
    approx: bool = False  # диапазон или «около»
    needs_review: bool = False
    reason: str | None = None

    @property
    def status(self) -> str:
        if self.needs_review:
            return "needs_review"
        return "to_taste" if self.qty is None else "ok"


def _normalize(raw: str) -> str:
    s = raw.replace("\xa0", " ").replace("\t", " ").lower().replace("ё", "е")
    s = _HALF_UNIT.sub(lambda m: "0.5 кг " if m[1].startswith("кило") else f"0.5 {m[1]} ", s)
    s = re.sub(r"\bполтор[аы]\b", "1.5", s)
    return re.sub(r"\s+", " ", s).strip()


def _pick_quantity(text: str) -> tuple[Quantity, str | None, int] | None:
    """Выбирает количество: первое с единицей, иначе первое «голое» число.

    Возвращает (количество, код единицы, конец единицы или конец числа).
    """
    first_bare: tuple[Quantity, str | None, int] | None = None
    for q in find_quantities(text):
        pos = q.end
        while pos < len(text) and text[pos] == " ":
            pos += 1
        unit = match_unit(text, pos)
        if unit:
            return q, unit[0], unit[1]
        if first_bare is None:
            first_bare = (q, None, q.end)
    return first_bare


def _bare_unit(text: str) -> tuple[Quantity, str, int] | None:
    """Единица без числа («щепотка соли», «пучок укропа») значит один."""
    for m in re.finditer(r"(?<![а-яе])(?=[а-яе])", text):
        unit = match_unit(text, m.start())
        if unit:
            return Quantity(1.0, 1.0, m.start(), unit[1]), unit[0], unit[1]
    return None


def _cut(text: str, q: Quantity, end: int) -> str:
    return f"{text[: q.start]} {text[end:]}"


def _locate(outer: str, inner: str) -> tuple[tuple[Quantity, str | None, int] | None, str]:
    """Находит количество и возвращает его вместе с названием без количества.

    Приоритет: число с единицей вне скобок, число с единицей в скобках, «голое»
    число, единица без числа («щепотка»). Название берётся из текста вне скобок.
    """
    out = _pick_quantity(outer)
    inn = _pick_quantity(inner) if inner else None
    if out and out[1]:
        return out, _cut(outer, out[0], out[2])
    if inn and inn[1]:
        return inn, outer
    if out:
        return out, _cut(outer, out[0], out[2])
    if inn:
        return inn, outer
    if bare := _bare_unit(outer):
        return bare, _cut(outer, bare[0], bare[2])
    return None, outer


def _clean_name(text: str, keep_list: bool = False) -> str:
    """Название без служебных слов.

    По умолчанию текст после запятой отбрасывается как пояснение («лук, нарезанный»).
    `keep_list` оставляет всё: «соль, перец — по вкусу» — это два продукта, и решать,
    как их разделить, должен справочник, а не запятая.
    """
    text = _APPROX.sub(" ", text)
    if keep_list:
        name = re.sub(r"\s+", " ", text).strip(_EDGE_PUNCT)
        return re.sub(r"\s[-–—]\s", " ", name).strip(_EDGE_PUNCT)
    # запятая-разделитель отсекает пояснение, десятичная («3,2%») нет
    for part in re.split(r"[;,](?!\d)", text):
        name = re.sub(r"\s+", " ", part).strip(_EDGE_PUNCT)
        name = re.sub(r"\s[-–—]\s", " ", name).strip(_EDGE_PUNCT)
        if name:
            return name
    return ""


def parse_line(raw: str) -> ParsedLine:
    text = _normalize(raw)
    approx = bool(_APPROX.search(text))

    optional = False
    if m := _TO_TASTE.search(text):
        optional = True
        text = f"{text[: m.start()]} {text[m.end() :]}"

    # Количество ищем сначала вне скобок; если там пусто, то внутри («Мука (200 г)»).
    inner = " ".join(_PAREN.findall(text))
    outer = _PAREN.sub(" ", text)
    picked, name_source = _locate(outer, inner)

    name = _clean_name(name_source, keep_list=optional and picked is None)

    qty: float | None = None
    unit: str | None = None
    source_unit: str | None = None
    if picked is not None:
        q, code, _ = picked
        source_unit = code or "pcs"
        qty, unit = to_base(q.high, source_unit)
        approx = approx or q.is_range

    reason: str | None = None
    if not name:
        reason = REASON_NO_NAME
    elif qty is None and not optional:
        reason = REASON_NO_QUANTITY

    return ParsedLine(
        raw=raw,
        name=name,
        qty=qty,
        unit=unit,
        source_unit=source_unit,
        optional=optional,
        approx=approx,
        needs_review=reason is not None,
        reason=reason,
    )
