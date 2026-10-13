"""Черновик рецепта из строк ингредиентов: разбор, сопоставление, пересчёт на порцию.

Черновик (status=draft) пара проверяет и подтверждает. Формат `to_recipe_input()`
совпадает с `RecipeInput` из docs/openapi.yaml; `ingredient_id` здесь — id справочника
(в базе это `ingredients.external_ref`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

from importers.directory import Directory
from importers.ingredient_line import ParsedLine, parse_line

# Единицы, которые для продукта и есть его «штука» (так он продаётся): головка
# чеснока, пучок укропа, банка кукурузы. Остальные штучные меры (зубчик, веточка,
# ломтик) переводятся в граммы через вес меры в справочнике.
CANONICAL_PIECE_UNITS: Final = frozenset({"pcs", "head", "bunch", "can", "pack", "bottle"})

MAX_SERVINGS: Final = 50

REASON_NO_MATCH: Final = "no_match"
REASON_AMBIGUOUS: Final = "ambiguous"
REASON_UNCERTAIN: Final = "uncertain"  # выбран по положению в названии, нужна проверка
REASON_UNIT_UNKNOWN: Final = "unit_unknown"  # «3 веточки» продукта без веса веточки

WARNING_SERVINGS_UNKNOWN: Final = "servings_unknown"
WARNING_NO_INGREDIENTS: Final = "no_ingredients"

_LIST_SPLIT: Final = re.compile(r"\s*,\s*|\s+и\s+")


@dataclass(frozen=True)
class DraftLine:
    raw_text: str
    name: str
    ingredient_id: str | None
    qty_per_serving: float
    unit: str  # g | ml | pcs
    optional: bool = False
    approx: bool = False
    needs_review: bool = False
    reason: str | None = None
    candidates: tuple[str, ...] = ()
    confidence: float = 0.0


@dataclass(frozen=True)
class RecipeDraft:
    title: str
    default_servings: int
    lines: tuple[DraftLine, ...]
    source_url: str | None = None
    warnings: tuple[str, ...] = ()
    tags: tuple[str, ...] = field(default=())

    @property
    def review_count(self) -> int:
        return sum(1 for line in self.lines if line.needs_review)

    def to_recipe_input(self) -> dict[str, Any]:
        """Тело запроса по схеме RecipeInput (status=draft)."""
        return {
            "title": self.title,
            "default_servings": self.default_servings,
            "source_url": self.source_url,
            "tags": list(self.tags),
            "status": "draft",
            "ingredients": [
                {
                    "ingredient_id": line.ingredient_id,
                    "qty_per_serving": line.qty_per_serving,
                    "unit": line.unit,
                    "optional": line.optional,
                    "raw_text": line.raw_text,
                    "needs_review": line.needs_review,
                }
                for line in self.lines
            ],
        }


def parse_servings(value: object) -> int | None:
    """Число порций из recipeYield: 4, "4 порции", ["4", "4 servings"], "на 6 персон"."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        n = int(value)
    elif isinstance(value, str):
        m = re.search(r"\d+", value)
        if not m:
            return None
        n = int(m[0])
    elif isinstance(value, list | tuple):
        for item in value:
            if (n_item := parse_servings(item)) is not None:
                return n_item
        return None
    else:
        return None
    return n if 1 <= n <= MAX_SERVINGS else None


def _names(parsed: ParsedLine) -> list[str]:
    """«соль, перец — по вкусу» — два продукта; строки с количеством не делим."""
    if parsed.optional and parsed.qty is None:
        parts = [p for p in _LIST_SPLIT.split(parsed.name) if p]
        if len(parts) > 1:
            return parts
    return [parsed.name]


def _line(raw: str, parsed: ParsedLine, name: str, servings: int, d: Directory) -> DraftLine:
    m = d.match(name) if name else None
    ingredient_id = m.ingredient_id if m else None

    qty = parsed.qty or 0.0
    unit = parsed.unit or "g"
    reason = parsed.reason
    if reason is None and m is not None and ingredient_id is None:
        reason = REASON_AMBIGUOUS if m.ambiguous else REASON_NO_MATCH
    elif reason is None and m is not None and m.uncertain:
        reason = REASON_UNCERTAIN
    if (
        reason is None
        and ingredient_id is not None
        and parsed.qty is not None
        and parsed.unit == "pcs"
        and parsed.source_unit not in CANONICAL_PIECE_UNITS
    ):
        weight = d.get(ingredient_id).unit_weights_g.get(parsed.source_unit or "")
        if weight:
            qty, unit = parsed.qty * weight, "g"
        else:
            reason = REASON_UNIT_UNKNOWN

    return DraftLine(
        raw_text=raw,
        name=name,
        ingredient_id=ingredient_id,
        qty_per_serving=round(qty / servings, 3),
        unit=unit,
        optional=parsed.optional,
        approx=parsed.approx,
        needs_review=reason is not None,
        reason=reason,
        candidates=m.candidates if m else (),
        confidence=m.confidence if m else 0.0,
    )


def build_draft(
    title: str,
    ingredient_lines: list[str],
    directory: Directory,
    *,
    servings: object = None,
    source_url: str | None = None,
) -> RecipeDraft:
    warnings: list[str] = []
    n = parse_servings(servings)
    if n is None:
        warnings.append(WARNING_SERVINGS_UNKNOWN)
        n = 1

    lines: list[DraftLine] = []
    for raw in ingredient_lines:
        parsed = parse_line(raw)
        for name in _names(parsed):
            lines.append(_line(raw, parsed, name, n, directory))
    if not lines:
        warnings.append(WARNING_NO_INGREDIENTS)

    return RecipeDraft(
        title=title.strip(),
        default_servings=n,
        lines=tuple(lines),
        source_url=source_url,
        warnings=tuple(warnings),
    )
