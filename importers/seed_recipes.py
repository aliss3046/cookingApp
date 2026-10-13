"""Сборка стартового набора блюд: db/seeds/recipes_source.json -> db/seeds/recipes.json.

Источник — обычные строки ингредиентов («Говядина — 500 г») на указанное число порций.
Сборка прогоняет их через тот же разбор и справочник, что и импорт по ссылке, и **падает**,
если хоть одна строка не разобрана или не сопоставлена: в базу попадают только чистые данные.

    python -m importers.seed_recipes          # пересобрать db/seeds/recipes.json
    python -m importers.seed_recipes --check  # проверить, что файл соответствует источнику
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from importers.directory import Directory, load_directory
from importers.draft import build_draft

SEEDS: Final = Path(__file__).resolve().parent.parent / "db" / "seeds"
SOURCE: Final = SEEDS / "recipes_source.json"
OUTPUT: Final = SEEDS / "recipes.json"
MAX_SERVINGS: Final = 12


class SeedError(Exception):
    """В источнике есть строки, которые нельзя превратить в структурные данные."""


def build_seed(source: list[dict[str, Any]], directory: Directory) -> list[dict[str, Any]]:
    problems: list[str] = []
    slugs: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in source:
        slug, title = item["slug"], item["title"]
        if slug in slugs:
            problems.append(f"{slug}: повторяющийся slug")
        slugs.add(slug)
        if not 1 <= item["servings"] <= MAX_SERVINGS:
            problems.append(f"{slug}: порций {item['servings']} вне 1..{MAX_SERVINGS}")
        if not item.get("tags"):
            problems.append(f"{slug}: нет тегов")

        draft = build_draft(title, item["lines"], directory, servings=item["servings"])
        for line in draft.lines:
            if line.needs_review:
                problems.append(f"{slug}: «{line.raw_text}» -> {line.reason} {line.candidates}")
        if draft.warnings:
            problems.append(f"{slug}: предупреждения {draft.warnings}")

        recipe = draft.to_recipe_input()
        out.append(
            {
                "slug": slug,
                "title": recipe["title"],
                "default_servings": recipe["default_servings"],
                "tags": item["tags"],
                "status": "confirmed",
                "ingredients": [
                    {
                        "ingredient_id": x["ingredient_id"],
                        "qty_per_serving": x["qty_per_serving"],
                        "unit": x["unit"],
                        "optional": x["optional"],
                        "raw_text": x["raw_text"],
                    }
                    for x in recipe["ingredients"]
                ],
            }
        )
    if problems:
        raise SeedError("\n".join(problems))
    return out


def dumps(data: list[dict[str, Any]]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m importers.seed_recipes")
    parser.add_argument("--check", action="store_true", help="не писать, только сверить файл")
    args = parser.parse_args(argv)

    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    try:
        text = dumps(build_seed(source, load_directory()))
    except SeedError as e:
        print(f"Стартовый набор не собран:\n{e}", file=sys.stderr)
        return 1
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != text:
            print("db/seeds/recipes.json устарел: запустите python -m importers.seed_recipes")
            return 1
        print(f"OK: {len(source)} блюд, файл актуален")
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"Записано {len(source)} блюд в {OUTPUT.name}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
