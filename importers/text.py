"""Нормализация текста для сопоставления названий: токены и простой стеммер.

Стеммер грубый, без словарей: отрезает одно окончание и сводит беглую гласную
(«перец/перца», «кабачок/кабачки»). Его задача не лингвистика, а одинаковый
результат для названия в справочнике и в строке рецепта. Формы, которые он не
сводит («яйца/яиц»), добавляются в справочник синонимами.
"""

from __future__ import annotations

import re
from typing import Final

_ENDINGS: Final = sorted(
    [
        # прилагательные и причастия
        "ыми", "ими", "ого", "его", "ому", "ему", "ая", "яя", "ое", "ее", "ые", "ие",
        "ый", "ий", "ой", "ую", "юю", "ых", "их", "ым", "им", "ей",
        # существительные
        "ами", "ями", "ах", "ях", "ов", "ев", "ом", "ем", "ам", "ям",
        "а", "я", "ы", "и", "у", "ю", "е", "о", "ь", "й",
    ],
    key=len,
    reverse=True,
)  # fmt: skip
_MIN_STEM: Final = 3
_FLEETING: Final = (("ец", "ц"), ("ок", "к"), ("ек", "к"))

# Служебные слова и описания размера/свежести не меняют продукт.
_STOP_WORDS: Final = {"и", "в", "во", "на", "с", "со", "для", "из", "по", "или", "без", "от", "к"}
_DESCRIPTORS: Final = {
    "свежий", "свежая", "свежие", "крупный", "крупная", "крупные", "средний", "средняя",
    "средние", "небольшой", "небольшая", "небольшие", "мелкий", "мелкая", "мелкие",
    "большой", "большая", "большие", "спелый", "спелые", "охлажденный", "охлажденное",
    "очищенный", "очищенные", "нарезанный", "нарезанные",
}  # fmt: skip


def stem(word: str) -> str:
    w = word
    for ending in _ENDINGS:
        # длинное окончание требует основы длиннее: иначе «салями» станет «сал» (как «сало»)
        min_stem = _MIN_STEM + 1 if len(ending) >= 3 else _MIN_STEM
        if w.endswith(ending) and len(w) - len(ending) >= min_stem:
            w = w[: -len(ending)]
            break
    if len(w) >= 5:
        for tail, short in _FLEETING:
            if w.endswith(tail):
                w = w[: -len(tail)] + short
                break
    return w


_DESCRIPTOR_STEMS: Final = {stem(w) for w in _DESCRIPTORS}


def normalize(text: str) -> str:
    s = text.lower().replace("ё", "е").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def tokens(text: str) -> list[str]:
    """Слова без чисел, процентов и знаков препинания."""
    return re.findall(r"[a-zа-я]+", normalize(text))


def stems(text: str) -> frozenset[str]:
    """Набор основ значимых слов: порядок слов не важен («масло сливочное»)."""
    out = set()
    for t in tokens(text):
        if t in _STOP_WORDS:
            continue
        s = stem(t)
        if s in _DESCRIPTOR_STEMS:
            continue
        out.add(s)
    return frozenset(out)
