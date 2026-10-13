"""Единицы измерения из рецептов и их перевод в базовые (г, мл, шт).

Модель корзины считает г и мл равными (1 мл ≈ 1 г), поэтому плотность здесь
не используется. Значения ниже — общие для всех продуктов; уточнение под
конкретный ингредиент (ст. ложка соли тяжелее ст. ложки воды) делается через
справочник ингредиентов позже.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

G: Final = "g"
ML: Final = "ml"
PCS: Final = "pcs"


@dataclass(frozen=True)
class UnitDef:
    code: str
    base: str  # g | ml | pcs
    factor: float  # сколько базовых единиц в одной


# Допущения: стакан = 200 мл, ст. ложка = 15, ч. ложка = 5, щепотка = 0.5 г,
# горсть = 30 г. «Банка», «пачка», «зубчик» и т. п. считаются штуками: вес и
# фасовка берутся из справочника и каталога магазина.
UNIT_DEFS: Final[dict[str, UnitDef]] = {
    u.code: u
    for u in [
        UnitDef("g", G, 1),
        UnitDef("kg", G, 1000),
        UnitDef("ml", ML, 1),
        UnitDef("l", ML, 1000),
        UnitDef("tbsp", ML, 15),
        UnitDef("dsp", ML, 10),
        UnitDef("tsp", ML, 5),
        UnitDef("cup", ML, 200),
        UnitDef("pinch", G, 0.5),
        UnitDef("handful", G, 30),
        UnitDef("pcs", PCS, 1),
        UnitDef("clove", PCS, 1),
        UnitDef("bunch", PCS, 1),
        UnitDef("can", PCS, 1),
        UnitDef("pack", PCS, 1),
        UnitDef("bottle", PCS, 1),
        UnitDef("slice", PCS, 1),
        UnitDef("head", PCS, 1),
        UnitDef("sprig", PCS, 1),
        UnitDef("cube", PCS, 1),
    ]
}

_END = r"(?![а-яе])"  # после короткого сокращения не должно идти продолжение слова

# Шаблоны для текста в нижнем регистре, «ё» заменена на «е».
# Порядок важен: более длинные и специфичные варианты раньше коротких.
_PATTERNS: Final[list[tuple[str, str]]] = [
    ("tbsp", rf"столов\w*\s+ложк\w*|стол\.?\s*ложк\w*|ст\.?\s*л{_END}\.?|ст\.?\s*ложк\w*"),
    ("dsp", r"десертн\w*\s+ложк\w*"),
    ("tsp", rf"чайн\w*\s+ложк\w*|ч\.?\s*л{_END}\.?|ч\.?\s*ложк\w*"),
    ("cup", r"стакан\w*|чашк\w*"),
    ("kg", rf"кг{_END}\.?|килограмм\w*|кило{_END}"),
    ("g", rf"грамм\w*|гр{_END}\.?|г{_END}\.?"),
    ("ml", rf"мл{_END}\.?|миллилитр\w*"),
    ("l", rf"литр\w*|л{_END}\.?"),
    ("pcs", rf"шт{_END}\.?|штук\w*|штучк\w*"),
    ("clove", r"зубчик\w*|зубок|зубк\w*"),
    ("pinch", r"щепот\w*"),
    ("handful", r"горст\w*|пригорш\w*"),
    ("bunch", r"пучк\w*|пучок"),
    ("can", r"банк\w*"),
    ("pack", r"упаковк\w*|пакет\w*|пачк\w*|пачек"),
    ("bottle", r"бутыл\w*"),
    ("slice", r"ломтик\w*|кусочек|кусочк\w*|кусок|куск\w*|долек|дольк\w*"),
    ("head", r"головк\w*|кочан\w*"),
    ("sprig", r"веточк\w*|веток|ветк\w*|стебел\w*|стебл\w*"),
    ("cube", r"кубик\w*"),
]

_UNIT_RE: Final = re.compile("|".join(f"(?P<{code}>{pattern})" for code, pattern in _PATTERNS))


def match_unit(text: str, pos: int) -> tuple[str, int] | None:
    """Единица, начинающаяся ровно с позиции pos: (код, конец) или None."""
    m = _UNIT_RE.match(text, pos)
    if not m:
        return None
    return m.lastgroup, m.end()  # type: ignore[return-value]


def to_base(qty: float, code: str) -> tuple[float, str]:
    """Переводит количество в базовую единицу: (число, g|ml|pcs)."""
    u = UNIT_DEFS[code]
    return qty * u.factor, u.base
