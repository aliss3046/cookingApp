"""Справочник ингредиентов и сопоставление названия из рецепта с ним.

Справочник лежит в db/seeds/ingredients.json: его загружает в базу разработчик БД
(таблица `ingredients`, поле `external_ref` = `id` справочника).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from importers.text import stems

DEFAULT_PATH: Final = Path(__file__).resolve().parent.parent / "db" / "seeds" / "ingredients.json"

CONFIDENCE_EXACT: Final = 1.0  # совпали все значимые слова
CONFIDENCE_CONTAINED: Final = 0.8  # название справочника целиком внутри строки, есть лишние слова
CANDIDATES_LIMIT: Final = 3


@dataclass(frozen=True)
class Ingredient:
    id: str
    name: str
    synonyms: tuple[str, ...] = ()
    group: str = ""
    # вес «штуки», в которой продукт обычно продаётся (головка чеснока, пучок укропа)
    piece_weight_g: float | None = None
    # вес других мер для этого продукта: зубчик, веточка, ломтик
    unit_weights_g: Mapping[str, float] = field(default_factory=dict)

    @property
    def aliases(self) -> tuple[str, ...]:
        return (self.name, *self.synonyms)


@dataclass(frozen=True)
class Match:
    ingredient_id: str | None
    confidence: float
    # Кандидаты для выбора пары: при неоднозначности или когда совпадения нет
    candidates: tuple[str, ...] = ()
    alias: str | None = None

    @property
    def ambiguous(self) -> bool:
        return self.ingredient_id is None and len(self.candidates) > 1


class Directory:
    def __init__(self, items: Iterable[Ingredient]):
        self._items: dict[str, Ingredient] = {}
        self._aliases: list[tuple[frozenset[str], str, str]] = []  # (основы, id, псевдоним)
        for it in items:
            if it.id in self._items:
                raise ValueError(f"duplicate ingredient id {it.id!r}")
            self._items[it.id] = it
            for alias in it.aliases:
                s = stems(alias)
                if s:
                    self._aliases.append((s, it.id, alias))

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, ingredient_id: object) -> bool:
        return ingredient_id in self._items

    def get(self, ingredient_id: str) -> Ingredient:
        return self._items[ingredient_id]

    def match(self, name: str) -> Match:
        """Сопоставляет название из строки рецепта с ингредиентом.

        Псевдоним подходит, если все его значимые слова есть в названии. Из
        подходящих побеждает самый длинный: «сливочное масло» точнее «масла».
        Если лучших несколько у разных ингредиентов, результат неоднозначен.
        """
        query = stems(name)
        if not query:
            return Match(None, 0.0)

        best: dict[str, tuple[int, str]] = {}  # id -> (длина псевдонима, псевдоним)
        overlap: dict[str, int] = {}
        for alias_stems, ing_id, alias in self._aliases:
            common = len(alias_stems & query)
            if common:
                overlap[ing_id] = max(overlap.get(ing_id, 0), common)
            if alias_stems <= query:
                size = len(alias_stems)
                if size > best.get(ing_id, (0, ""))[0]:
                    best[ing_id] = (size, alias)

        if not best:
            ranked = sorted(overlap, key=lambda i: (-overlap[i], i))
            return Match(None, 0.0, tuple(ranked[:CANDIDATES_LIMIT]))

        top = max(size for size, _ in best.values())
        winners = sorted(i for i, (size, _) in best.items() if size == top)
        if len(winners) > 1:
            return Match(None, 0.0, tuple(winners[:CANDIDATES_LIMIT]))

        winner = winners[0]
        confidence = CONFIDENCE_EXACT if top == len(query) else CONFIDENCE_CONTAINED
        return Match(winner, confidence, (winner,), best[winner][1])


def load_directory(path: Path = DEFAULT_PATH) -> Directory:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Directory(
        Ingredient(
            id=x["id"],
            name=x["name"],
            synonyms=tuple(x.get("synonyms", ())),
            group=x.get("group", ""),
            piece_weight_g=x.get("piece_weight_g"),
            unit_weights_g=dict(x.get("unit_weights_g", {})),
        )
        for x in raw
    )
