"""Что воркеру цен нужно от хранилища. Реализацию на Postgres пишет разработчик БД.

Контракт (docs/schema.md): цены только добавляются; товары обновляются по (магазин, внешний id);
сопоставление ингредиента заменяется целиком для пары (магазин, ингредиент).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from prices.matching import Match
from prices.normalize import NormalizedOffer


@dataclass(frozen=True)
class RunStats:
    store: str
    location_key: str
    started_at: datetime
    finished_at: datetime | None = None
    pages: int = 0
    offers_found: int = 0
    parsed: int = 0  # карточек, превращённых в товар с ценой
    parse_errors: int = 0
    matched_auto: int = 0
    matched_confirm: int = 0
    skipped_by_robots: int = 0
    # причины остановки и подозрений
    blocked: str | None = None
    budget_exceeded: bool = False
    suspicious: str | None = None  # доля разобранных упала: вероятно, сменилась вёрстка
    written: bool = False
    notes: tuple[str, ...] = field(default=())


class PriceStore(Protocol):
    def upsert_products(self, store: str, offers: Sequence[NormalizedOffer]) -> None: ...

    def add_prices(
        self, store: str, location_key: str, offers: Sequence[NormalizedOffer]
    ) -> None: ...

    def replace_mapping(
        self, store: str, ingredient_id: str, matches: Sequence[Match], matcher_version: str
    ) -> None: ...

    def last_run(self, store: str, location_key: str) -> RunStats | None: ...

    def save_run(self, stats: RunStats) -> None: ...
