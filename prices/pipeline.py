"""Конвейер цен: категории -> карточки -> товары и цены -> подбор под ингредиенты -> хранилище.

Без отдельных «провайдеров»: что читать, задаёт профиль магазина (prices/stores.json), как
читать, определяют форматы данных страницы (prices/listing.py). Магазин должен быть включён
владельцем проекта.

Защита данных: если число разобранных карточек резко упало по сравнению с прошлым запуском
(признак смены вёрстки), ничего не записывается и ставится пометка `suspicious`. По плану алерт
при падении больше чем на 30%.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Final, Protocol

from importers.directory import Directory
from importers.errors import FetchFailed
from prices.listing import extract_offers
from prices.matching import MATCHER_VERSION, Match, Matcher
from prices.normalize import NormalizedOffer, PriceParseError, normalize_offer
from prices.politeness import BudgetExceeded, NotAllowed, StoreBlocked
from prices.ports import PriceStore, RunStats
from prices.profile import CategorySpec, StoreProfile

SUSPICIOUS_DROP: Final = 0.30
MIN_PREVIOUS_FOR_ALERT: Final = 10


class Fetcher(Protocol):
    def get(self, url: str) -> str: ...


def _ingredient_ids(spec: CategorySpec, directory: Directory) -> list[str]:
    ids = [i for i in spec.ingredients if i in directory]
    for ing in directory.ingredients():
        if ing.group in spec.groups and ing.id not in ids:
            ids.append(ing.id)
    return ids


def run_store(
    profile: StoreProfile,
    location_key: str,
    *,
    fetcher: Fetcher,
    directory: Directory,
    matcher: Matcher,
    store: PriceStore,
    known_brands: Iterable[str] = (),
    now: datetime | None = None,
) -> RunStats:
    profile.require_enabled()
    started = now or datetime.now(UTC)
    brands = list(known_brands)

    pages = offers_found = parsed = parse_errors = skipped_robots = 0
    blocked: str | None = None
    budget_exceeded = False
    notes: list[str] = []
    products: dict[str, NormalizedOffer] = {}
    mapping: dict[str, dict[str, Match]] = {}

    for spec in profile.categories:
        try:
            page = fetcher.get(spec.url)
        except NotAllowed:
            skipped_robots += 1
            continue
        except StoreBlocked as e:
            blocked = e.reason
            break
        except BudgetExceeded:
            budget_exceeded = True
            break
        except FetchFailed as e:
            notes.append(f"{spec.url}: {e}")
            continue
        pages += 1

        listing = extract_offers(page, store=profile.code, now=started, category=spec.note)
        offers_found += len(listing.offers) + listing.skipped
        parse_errors += listing.skipped
        normalized: list[NormalizedOffer] = []
        for raw in listing.offers:
            try:
                normalized.append(normalize_offer(raw, brands))
            except PriceParseError:
                parse_errors += 1
        parsed += len(normalized)
        products.update({o.external_id: o for o in normalized})

        for ingredient_id in _ingredient_ids(spec, directory):
            bucket = mapping.setdefault(ingredient_id, {})
            for m in matcher.shortlist(ingredient_id, normalized):
                bucket.setdefault(m.external_id, m)

    stats = RunStats(
        store=profile.code,
        location_key=location_key,
        started_at=started,
        finished_at=datetime.now(UTC) if now is None else started,
        pages=pages,
        offers_found=offers_found,
        parsed=parsed,
        parse_errors=parse_errors,
        matched_auto=sum(m.verdict == "auto" for b in mapping.values() for m in b.values()),
        matched_confirm=sum(m.verdict == "confirm" for b in mapping.values() for m in b.values()),
        skipped_by_robots=skipped_robots,
        blocked=blocked,
        budget_exceeded=budget_exceeded,
        notes=tuple(notes),
    )

    suspicious = None
    if blocked is None and not budget_exceeded:
        suspicious = _suspicion(stats, store.last_run(profile.code, location_key))
    stats = replace(stats, suspicious=suspicious)

    if blocked is None and not budget_exceeded and suspicious is None and parsed > 0:
        store.upsert_products(profile.code, list(products.values()))
        store.add_prices(profile.code, location_key, list(products.values()))
        for ingredient_id, bucket in mapping.items():
            store.replace_mapping(
                profile.code, ingredient_id, list(bucket.values()), MATCHER_VERSION
            )
        stats = replace(stats, written=True)
    store.save_run(stats)
    return stats


def _suspicion(stats: RunStats, previous: RunStats | None) -> str | None:
    if stats.pages and stats.parsed == 0:
        return "ни одной карточки не разобрано: вероятно, сменился формат страниц"
    if (
        previous is not None
        and previous.parsed >= MIN_PREVIOUS_FOR_ALERT
        and stats.parsed < previous.parsed * (1 - SUSPICIOUS_DROP)
    ):
        return (
            f"разобрано {stats.parsed} карточек против {previous.parsed} в прошлый раз "
            f"(падение больше {SUSPICIOUS_DROP:.0%}): вероятно, сменилась вёрстка"
        )
    return None
