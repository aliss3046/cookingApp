"""Импорт рецепта по ссылке из командной строки.

    python -m importers https://example.com/recipe
    python -m importers --html saved_page.html

Печатает JSON: `recipe` — тело запроса по схеме RecipeInput (status=draft),
`review` — строки, которые паре нужно проверить, `warnings` — замечания к рецепту.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TextIO

from importers.directory import Directory, load_directory
from importers.draft import RecipeDraft
from importers.recipe_page import RecipeImportError, fetch_html, import_from_html

EXIT_OK = 0
EXIT_IMPORT_FAILED = 1


def draft_to_json(draft: RecipeDraft) -> dict[str, Any]:
    return {
        "recipe": draft.to_recipe_input(),
        "review": [
            {
                "raw_text": line.raw_text,
                "name": line.name,
                "reason": line.reason,
                "candidates": list(line.candidates),
            }
            for line in draft.lines
            if line.needs_review
        ],
        "warnings": list(draft.warnings),
        "summary": {
            "lines": len(draft.lines),
            "needs_review": draft.review_count,
        },
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    fetch: Callable[[str], str] = fetch_html,
    directory: Directory | None = None,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m importers",
        description="Импорт рецепта по ссылке в формат бэкенда (RecipeInput, status=draft).",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("url", nargs="?", help="ссылка на страницу рецепта")
    source.add_argument("--html", type=Path, help="сохранённая страница вместо загрузки по ссылке")
    parser.add_argument("--compact", action="store_true", help="JSON в одну строку")
    args = parser.parse_args(argv)

    directory = directory or load_directory()
    try:
        if args.html is not None:
            page = args.html.read_text(encoding="utf-8", errors="replace")
            draft = import_from_html(page, directory)
        else:
            draft = import_from_html(fetch(args.url), directory, source_url=args.url)
    except (RecipeImportError, OSError) as e:
        print(f"Не удалось импортировать рецепт: {e}", file=err)
        return EXIT_IMPORT_FAILED

    indent = None if args.compact else 2
    json.dump(draft_to_json(draft), out, ensure_ascii=False, indent=indent)
    out.write("\n")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
