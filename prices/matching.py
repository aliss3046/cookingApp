"""Подбор товаров магазина под ингредиент. Правила и пороги: docs/product-matching.md, ADR-0007.

Принцип: точность важнее полноты. Сначала отказы (другой ингредиент, не еда, другая форма,
исключение), потом оценка 0..1 и вердикт: `auto` (в список без вопросов), `confirm` (пара
подтверждает), `reject`. LLM нет; всё детерминировано и проверяется эталонным набором.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from importers.directory import Directory
from importers.text import normalize, stem
from prices.normalize import NormalizedOffer

DEFAULT_RULES: Final = Path(__file__).resolve().parent / "matching_rules.json"
# Версия правил: пишется рядом с сопоставлением, чтобы после смены правил пересчитать старое.
MATCHER_VERSION: Final = "1"

AUTO_AT: Final = 0.85
CONFIRM_AT: Final = 0.60
TIE_CAP: Final = 0.55  # ингредиент выбран по положению слова при равенстве: только отказ
BASE_CLEAN: Final = 0.95  # в названии только слова ингредиента
BASE_ONE_EXTRA: Final = 0.75  # одно лишнее слово: до auto не дотягивает даже с категорией
BASE_MANY_EXTRA: Final = 0.60
BONUS_CATEGORY: Final = 0.05
PENALTY_PACK: Final = 0.30
DEFAULT_PER_GROUP: Final = 2
DEFAULT_LIMIT: Final = 12

Verdict = Literal["auto", "confirm", "reject"]

# Слова формы продукта. Совпадение формы товара и ингредиента обязательно.
_FORM_WORDS: Final = {
    "canned": ["консервированный", "консервы", "консервированные"],
    "frozen": ["замороженный", "замороженные", "заморозка", "замороженное"],
    "dried": ["сушёный", "сушеный", "сушёные", "сушеные", "сублимированный"],
    "pickled": ["маринованный", "маринованные", "маринованное"],
    "smoked": ["копчёный", "копченый", "копчёные", "копченые", "копчёное", "копченое"],
    "cured": ["вяленый", "вяленые", "вяленое"],
    "salted": ["солёный", "соленый", "солёные", "соленые", "засоленный", "малосольный"],
    "fermented": ["квашеный", "квашеные", "квашеная"],
    "fried": ["жареный", "жареные", "жареная", "жареное"],
}
_FORM_BY_STEM: Final = {stem(normalize(w)): form for form, ws in _FORM_WORDS.items() for w in ws}

_QUOTED: Final = re.compile(r"[«\"“„][^»\"”“]{2,40}[»\"”“]")
_PACK_TEXT: Final = re.compile(
    r"~?\d+(?:[.,]\d+)?\s*(?:%|кг|гр|г|мл|л|шт)(?![а-яёa-z])\.?"
    r"|\d+\s*[xх×]\s*\d+|№\s*\d+|[сc]\s?[0-3](?!\d)|\d+[-–]\d+|в/с|\d+",
    re.I,
)
_WORD: Final = re.compile(r"[A-Za-zА-Яа-яЁё]+")
_PERCENT: Final = re.compile(r"(\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?)\s*%")


@dataclass(frozen=True)
class Rules:
    includes: dict[str, frozenset[str]]
    exclude: dict[str, frozenset[str]]  # основы слов
    harmless: frozenset[str]  # основы
    category_groups: dict[str, frozenset[str]]
    any_category: tuple[str, ...]
    non_food: tuple[str, ...]
    dish_stems: frozenset[str]  # «по-корейски», «готовое блюдо»: это уже готовая еда, а не продукт
    pack_ranges: dict[str, tuple[float, float]]
    default_pack_range: tuple[float, float]


def load_rules(path: Path = DEFAULT_RULES) -> Rules:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    def stems_of(words: Iterable[str]) -> frozenset[str]:
        return frozenset(stem(normalize(w)) for w in words)

    return Rules(
        includes={k: frozenset(v) for k, v in raw.get("includes", {}).items()},
        exclude={k: stems_of(v) for k, v in raw.get("exclude", {}).items()},
        harmless=stems_of(raw.get("harmless", [])),
        category_groups={k: frozenset(v) for k, v in raw.get("category_groups", {}).items()},
        any_category=tuple(raw.get("any_category", [])),
        non_food=tuple(raw.get("non_food_words", [])),
        dish_stems=stems_of(raw.get("dish_words", [])),
        pack_ranges={k: (v[0], v[1]) for k, v in raw.get("pack_ranges", {}).items()},
        default_pack_range=tuple(raw.get("default_pack_range", [1, 50000])),  # type: ignore[arg-type]
    )


@dataclass(frozen=True)
class Match:
    ingredient_id: str
    store: str
    external_id: str
    score: float
    verdict: Verdict
    brand: str
    variant: str
    reasons: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return self.verdict != "reject"


def extract_variant(title: str) -> str:
    """Процент из названия: «3,2%». Диапазон сохраняется как есть. Нет — пусто."""
    m = _PERCENT.search(title or "")
    if not m:
        return ""
    return re.sub(r"\s+", "", m[1]).replace(".", ",") + "%"


def _forms(text: str) -> set[str]:
    return {
        _FORM_BY_STEM[s] for w in _WORD.findall(normalize(text)) if (s := stem(w)) in _FORM_BY_STEM
    }


class Matcher:
    def __init__(self, directory: Directory, rules: Rules | None = None):
        self._dir = directory
        self._rules = rules or load_rules()

    # -- публичное --

    def match(self, ingredient_id: str, offer: NormalizedOffer) -> Match:
        score, verdict, reasons = self._evaluate(ingredient_id, offer)
        return Match(
            ingredient_id=ingredient_id,
            store=offer.store,
            external_id=offer.external_id,
            score=round(score, 2),
            verdict=verdict,
            brand=offer.brand,
            variant=extract_variant(offer.title),
            reasons=tuple(reasons),
        )

    def shortlist(
        self,
        ingredient_id: str,
        offers: Iterable[NormalizedOffer],
        per_group: int = DEFAULT_PER_GROUP,
        limit: int = DEFAULT_LIMIT,
    ) -> list[Match]:
        """Лучшие подходящие товары: по `per_group` на (магазин, марка, вариант), всего `limit`.

        Пара выбирает марку и вариант, поэтому важно разнообразие, а не десять фасовок одной марки.
        """
        matches = [m for m in (self.match(ingredient_id, o) for o in offers) if m.accepted]
        matches.sort(key=lambda m: (-m.score, m.store, m.brand, m.external_id))
        taken: dict[tuple[str, str, str], int] = {}
        out: list[Match] = []
        for m in matches:
            key = (m.store, m.brand.lower(), m.variant)
            if taken.get(key, 0) >= per_group:
                continue
            taken[key] = taken.get(key, 0) + 1
            out.append(m)
            if len(out) == limit:
                break
        return out

    # -- оценка --

    def _accepted_ids(self, ingredient_id: str) -> frozenset[str]:
        return frozenset({ingredient_id}) | self._rules.includes.get(ingredient_id, frozenset())

    def _evaluate(
        self, ingredient_id: str, offer: NormalizedOffer
    ) -> tuple[float, Verdict, list[str]]:
        r = self._rules
        ingredient = self._dir.get(ingredient_id)
        title = offer.title or ""
        category = (offer.category or "").lower()

        def reject(reason: str) -> tuple[float, Verdict, list[str]]:
            return 0.0, "reject", [reason]

        if any(w in normalize(title) or w in category for w in r.non_food):
            return reject("not_food")

        core_text = title
        for phrase in (offer.brand,):
            if phrase:
                core_text = re.sub(re.escape(phrase), " ", core_text, flags=re.I)
        core_text = _QUOTED.sub(" ", core_text)
        core_text = _PACK_TEXT.sub(" ", core_text)
        words = _WORD.findall(core_text)

        # форма продукта: консервы, заморозка и т. д.
        product_form, ingredient_form = _forms(title), _forms(ingredient.name)
        if product_form != ingredient_form:
            diff = sorted(product_form ^ ingredient_form)
            return reject(f"form:{'/'.join(diff)}")

        kept = [w for w in words if stem(normalize(w)) not in r.harmless]
        m = self._dir.match(" ".join(kept))
        if m.ingredient_id is None:
            return reject("no_match")
        if m.ingredient_id not in self._accepted_ids(ingredient_id):
            return reject(f"other:{m.ingredient_id}")

        title_stems = {stem(normalize(w)) for w in words}
        for banned in r.exclude.get(ingredient_id, frozenset()):
            if banned in title_stems:
                return reject(f"excluded:{banned}")
        if dish := sorted(title_stems & r.dish_stems):
            return reject(f"dish:{dish[0]}")

        reasons: list[str] = []
        matched = {stem(normalize(w)) for w in _WORD.findall(normalize(m.alias or ""))}
        unknown = [
            w
            for i, w in enumerate(kept)
            if stem(normalize(w)) not in matched and not _brandish(w, i)
        ]
        if not unknown:
            score, label = BASE_CLEAN, "clean"
        elif len(unknown) == 1:
            score, label = BASE_ONE_EXTRA, "extra1"
        else:
            score, label = BASE_MANY_EXTRA, "extra2+"
        reasons.append(f"head:{label}")

        # Продукт называется первым словом: «Молоко …», «Сыр …». Если ингредиент упомянут позже
        # («Чипсы со вкусом сыра», «Пирог со сметаной»), это другой продукт.
        first = next((i for i, w in enumerate(kept) if stem(normalize(w)) in matched), None)
        if first != 0:
            return reject("not_head")

        verdict_cat = self._category(ingredient.group, category)
        if verdict_cat == "bad":
            return reject(f"category:{category}")
        if verdict_cat == "ok":
            score += BONUS_CATEGORY
            reasons.append("category")

        if not self._pack_plausible(ingredient.group, offer):
            score -= PENALTY_PACK
            reasons.append("pack")

        # ничья между ингредиентами: если подходят все претенденты (макароны ~ спирали), всё ок
        if m.tie and not set(m.candidates) <= self._accepted_ids(ingredient_id):
            score = min(score, TIE_CAP)
            reasons.append("tie")

        score = max(0.0, min(1.0, score))
        verdict: Verdict = (
            "auto" if score >= AUTO_AT else "confirm" if score >= CONFIRM_AT else "reject"
        )
        return score, verdict, reasons

    def _category(self, group: str, category: str) -> Literal["ok", "bad", "unknown"]:
        if not category:
            return "unknown"
        r = self._rules
        if any(k in category for k in r.any_category):
            return "unknown"
        groups = set()
        for key, gs in r.category_groups.items():
            if key in category:
                groups |= gs
        if not groups:
            return "unknown"
        return "ok" if group in groups else "bad"

    def _pack_plausible(self, group: str, offer: NormalizedOffer) -> bool:
        if offer.pack_qty is None or offer.pack_unit not in {"g", "ml"}:
            return True
        low, high = self._rules.pack_ranges.get(group, self._rules.default_pack_range)
        return low <= offer.pack_qty <= high


def _brandish(word: str, index: int) -> bool:
    """Слово, похожее на марку: латиница или заглавная не в начале названия."""
    return word.isascii() or (index > 0 and word[:1].isupper())
