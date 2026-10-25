"""Локальный прогон воркера на очереди в памяти, без базы.

    python -m jobs import https://example.com/recipe

Ставит задание импорта, как это делает Go-бэкенд, выполняет его воркером и печатает строку
таблицы jobs (статус, result или ошибку). В работе воркер запускается с очередью на Postgres.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TextIO

from importers.directory import Directory, load_directory
from importers.recipe_page import fetch_html
from jobs.handlers import default_handlers
from jobs.memory import MemoryJobQueue
from jobs.ports import DONE, KIND_IMPORT
from jobs.runner import Worker

EXIT_OK = 0
EXIT_FAILED = 1


def main(
    argv: Sequence[str] | None = None,
    *,
    fetch: Callable[[str], str] = fetch_html,
    directory: Directory | None = None,
    out: TextIO = sys.stdout,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m jobs")
    sub = parser.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="поставить и выполнить задание импорта рецепта")
    imp.add_argument("url")
    args = parser.parse_args(argv)

    queue = MemoryJobQueue()
    job_id = queue.add("local", KIND_IMPORT, {"url": args.url}, datetime.now(UTC))
    Worker(queue, default_handlers(directory or load_directory(), fetch=fetch)).run_once()
    row = queue.rows[job_id]
    json.dump(asdict(row), out, ensure_ascii=False, indent=2, default=str)
    out.write("\n")
    return EXIT_OK if row.status == DONE else EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
