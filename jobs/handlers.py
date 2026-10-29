"""Обработчики заданий по виду (`jobs.kind`). Обработчик получает params, возвращает result
или бросает JobFailure, если задание невыполнимо."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from importers.__main__ import draft_to_json
from importers.directory import Directory
from importers.recipe_page import RecipeImportError, fetch_html, import_from_html
from jobs.ports import ERR_IMPORT, ERR_VALIDATION, KIND_IMPORT, JobFailure

Handler = Callable[[Mapping[str, Any]], dict[str, Any]]


def import_recipe(
    params: Mapping[str, Any],
    *,
    directory: Directory,
    fetch: Callable[[str], str] = fetch_html,
) -> dict[str, Any]:
    """`POST /recipes/import`: params = {"url"}. Result — черновик рецепта (status=draft)
    и строки на проверку, как у `python -m importers`. Ингредиенты указаны кодом справочника
    (`ingredients.code`); сохраняет рецепт бэкенд после проверки парой."""
    url = params.get("url")
    if not isinstance(url, str) or not url.strip():
        raise JobFailure(ERR_VALIDATION, "в задании импорта нет ссылки (params.url)")
    url = url.strip()
    try:
        draft = import_from_html(fetch(url), directory, source_url=url)
    except RecipeImportError as e:
        raise JobFailure(ERR_IMPORT, str(e) or type(e).__name__) from e
    return draft_to_json(draft)


def default_handlers(
    directory: Directory, *, fetch: Callable[[str], str] = fetch_html
) -> dict[str, Handler]:
    """Виды, которые воркер уже умеет. `quote` (цены корзины) пока не берётся и ждёт в очереди."""
    return {KIND_IMPORT: lambda params: import_recipe(params, directory=directory, fetch=fetch)}
