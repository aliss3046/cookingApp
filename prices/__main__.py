"""Цены из командной строки.

    python -m prices dry-run --store magnit --html page.html --groups молочные,овощи
    python -m prices categories --html page.html
    python -m prices run --store magnit --location 992301 [--json out.json] [--pages-dir pages/]

`dry-run` и `categories` работают по сохранённой странице, без сети, и не требуют включения
магазина. `run` ходит на сайт и работает только для магазина, включённого владельцем проекта
в prices/stores.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from importers.directory import Directory, load_directory
from prices.fetcher import PoliteFetcher
from prices.listing import extract_categories, extract_offers
from prices.matching import Match, Matcher
from prices.memory_store import MemoryPriceStore
from prices.normalize import NormalizedOffer, PriceParseError, normalize_offer
from prices.pipeline import run_store
from prices.profile import ProfileError, StoreDisabled, StoreProfile, load_profiles
from prices.saved_pages import SavedPages

EXIT_OK = 0
EXIT_FAILED = 1


def _match_json(m: Match, product: NormalizedOffer | None = None) -> dict[str, Any]:
    shown = (
        {
            "title": product.title,
            "price": str(product.price),
            "price_per_kg": None if product.price_per_kg is None else str(product.price_per_kg),
            "in_stock": product.in_stock,
        }
        if product
        else {}
    )
    return {
        **shown,
        "external_id": m.external_id,
        "score": m.score,
        "verdict": m.verdict,
        "brand": m.brand,
        "variant": m.variant,
        "reasons": list(m.reasons),
    }


def _ingredient_ids(directory: Directory, groups: list[str], ingredients: list[str]) -> list[str]:
    ids = [i for i in ingredients if i in directory]
    ids += [i.id for i in directory.ingredients() if i.group in groups and i.id not in ids]
    return ids


def _dry_run(args: argparse.Namespace, directory: Directory, out: TextIO) -> int:
    page = Path(args.html).read_text(encoding="utf-8", errors="replace")
    now = datetime.now(UTC)
    listing = extract_offers(page, store=args.store, now=now)
    offers, errors = [], 0
    for raw in listing.offers:
        try:
            offers.append(normalize_offer(raw))
        except PriceParseError:
            errors += 1
    matcher = Matcher(directory)
    ids = _ingredient_ids(directory, _split(args.groups), _split(args.ingredients))
    result = {
        "strategy": listing.strategy,
        "cards": len(listing.offers),
        "skipped": listing.skipped,
        "price_errors": errors,
        "products": [
            {
                "id": o.external_id, "title": o.title, "price": str(o.price), "mode": o.sale_mode,
                "pack": [o.pack_qty, o.pack_unit], "price_per_kg": str(o.price_per_kg),
                "brand": o.brand,
            }
            for o in offers
        ],
        "shortlists": {
            i: [_match_json(m) for m in matcher.shortlist(i, offers)] for i in ids
        },
    }  # fmt: skip
    json.dump(result, out, ensure_ascii=False, indent=2)
    out.write("\n")
    return EXIT_OK


def _categories(args: argparse.Namespace, out: TextIO) -> int:
    page = Path(args.html).read_text(encoding="utf-8", errors="replace")
    for depth, cid, code, name in extract_categories(page):
        out.write(f"{'  ' * depth}{cid}-{code}\t{name}\n")
    return EXIT_OK


def _run(args: argparse.Namespace, profile: StoreProfile, directory: Directory, out: TextIO) -> int:
    store = MemoryPriceStore()
    stats = run_store(
        profile,
        args.location,
        fetcher=(
            SavedPages(args.pages_dir)
            if args.pages_dir
            else PoliteFetcher(
                min_delay_s=profile.min_delay_s, daily_limit=profile.daily_request_limit
            )
        ),
        directory=directory,
        matcher=Matcher(directory),
        store=store,
    )
    result = {
        "stats": {
            k: (str(v) if isinstance(v, datetime | tuple) else v) for k, v in vars(stats).items()
        },
        "shortlists": {
            ing: [_match_json(m, store.products.get((profile.code, m.external_id))) for m in ms]
            for (_, ing), (ms, _) in store.mapping.items()
        },
    }  # fmt: skip
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    else:
        out.write(text)
    return EXIT_FAILED if stats.blocked or stats.suspicious else EXIT_OK


def _split(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def main(
    argv: Sequence[str] | None = None,
    *,
    directory: Directory | None = None,
    profiles: dict[str, StoreProfile] | None = None,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m prices")
    sub = parser.add_subparsers(dest="cmd", required=True)
    dry = sub.add_parser("dry-run", help="разобрать сохранённую страницу, без сети")
    dry.add_argument("--store", required=True)
    dry.add_argument("--html", required=True)
    dry.add_argument("--groups", help="группы справочника через запятую")
    dry.add_argument("--ingredients", help="id ингредиентов через запятую")
    cat = sub.add_parser("categories", help="дерево категорий из сохранённой страницы")
    cat.add_argument("--html", required=True)
    run = sub.add_parser("run", help="прочитать категории магазина (только включённый магазин)")
    run.add_argument("--store", required=True)
    run.add_argument("--location", required=True, help="ключ адреса или магазина")
    run.add_argument("--json", help="записать результат в файл")
    run.add_argument(
        "--pages-dir", help="читать страницы, сохранённые из браузера, из папки (без сети)"
    )
    args = parser.parse_args(argv)

    if args.cmd == "categories":
        return _categories(args, out)
    directory = directory or load_directory()
    if args.cmd == "dry-run":
        return _dry_run(args, directory, out)

    try:
        loaded = profiles if profiles is not None else load_profiles()
        profile = loaded[args.store]
        profile.require_enabled()
    except KeyError:
        print(f"Нет профиля магазина «{args.store}» в prices/stores.json", file=err)
        return EXIT_FAILED
    except (ProfileError, StoreDisabled) as e:
        print(f"Не запущено: {e}", file=err)
        return EXIT_FAILED
    return _run(args, profile, directory, out)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
