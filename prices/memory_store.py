"""Хранилище цен в памяти: для тестов и сухого прогона. Ведёт себя по контракту prices/ports.py."""

from __future__ import annotations

from collections.abc import Sequence

from prices.matching import Match
from prices.normalize import NormalizedOffer
from prices.ports import RunStats


class MemoryPriceStore:
    def __init__(self) -> None:
        self.products: dict[tuple[str, str], NormalizedOffer] = {}
        self.prices: list[
            tuple[str, str, NormalizedOffer]
        ] = []  # (магазин, адрес, цена): только добавляются
        self.mapping: dict[tuple[str, str], tuple[tuple[Match, ...], str]] = {}
        self.runs: list[RunStats] = []

    def upsert_products(self, store: str, offers: Sequence[NormalizedOffer]) -> None:
        for o in offers:
            self.products[(store, o.external_id)] = o

    def add_prices(self, store: str, location_key: str, offers: Sequence[NormalizedOffer]) -> None:
        self.prices.extend((store, location_key, o) for o in offers)

    def replace_mapping(
        self, store: str, ingredient_id: str, matches: Sequence[Match], matcher_version: str
    ) -> None:
        self.mapping[(store, ingredient_id)] = (tuple(matches), matcher_version)

    def last_run(self, store: str, location_key: str) -> RunStats | None:
        for run in reversed(self.runs):
            if run.store == store and run.location_key == location_key and run.written:
                return run
        return None

    def save_run(self, stats: RunStats) -> None:
        self.runs.append(stats)
