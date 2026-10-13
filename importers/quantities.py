"""Числа в строках рецептов: «2», «1,5», «1/2», «1 1/2», «½», «2-3»."""

from __future__ import annotations

import re
from dataclasses import dataclass

_VULGAR = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}
_V = "".join(_VULGAR)

# Порядок важен: сначала составные («1 1/2», «1½»), затем дробь, затем десятичное.
NUMBER = (
    rf"(?:\d+\s*[{_V}]"
    r"|\d+\s+\d+\s*/\s*\d+"
    r"|\d+\s*/\s*\d+"
    r"|\d+(?:[.,]\d+)?"
    rf"|[{_V}])"
)

# Число или диапазон. Не берём числа внутри слов («С1»), проценты («3,2%»),
# хвосты десятичных и дробей.
QUANTITY_RE = re.compile(
    rf"(?<![\w.,/])(?P<lo>{NUMBER})"
    rf"(?:\s*[-–—]\s*(?P<hi>{NUMBER})|\s+до\s+(?P<hi2>{NUMBER}))?"
    r"(?!\s*%)(?![\d/]|[.,]\d)"
)


@dataclass(frozen=True)
class Quantity:
    low: float
    high: float
    start: int
    end: int

    @property
    def is_range(self) -> bool:
        return self.high != self.low


def to_float(text: str) -> float:
    """Переводит одно число из рецепта в float. Некорректное число — ValueError."""
    s = text.strip()
    if m := re.fullmatch(rf"(\d+)\s*([{_V}])", s):
        return int(m[1]) + _VULGAR[m[2]]
    if m := re.fullmatch(r"(\d+)\s+(\d+)\s*/\s*(\d+)", s):
        return int(m[1]) + _fraction(m[2], m[3])
    if m := re.fullmatch(r"(\d+)\s*/\s*(\d+)", s):
        return _fraction(m[1], m[2])
    if s in _VULGAR:
        return _VULGAR[s]
    return float(s.replace(",", "."))


def _fraction(num: str, den: str) -> float:
    if int(den) == 0:
        raise ValueError(f"zero denominator in {num}/{den}")
    return int(num) / int(den)


def find_quantities(text: str) -> list[Quantity]:
    """Все количества в строке по порядку. Числа с нулевым знаменателем пропускаются."""
    out: list[Quantity] = []
    for m in QUANTITY_RE.finditer(text):
        try:
            low = to_float(m["lo"])
            hi_text = m["hi"] or m["hi2"]
            high = to_float(hi_text) if hi_text else low
        except ValueError:
            continue
        if high < low:  # «5-3» — не диапазон, берём первое число
            high = low
        out.append(Quantity(low, high, m.start(), m.end()))
    return out
