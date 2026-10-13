"""Ошибки импорта рецепта."""

from __future__ import annotations


class RecipeImportError(Exception):
    """Базовая ошибка импорта рецепта."""


class BadUrl(RecipeImportError):
    pass


class DisallowedByRobots(RecipeImportError):
    pass


class PageTooLarge(RecipeImportError):
    pass


class FetchFailed(RecipeImportError):
    pass


class NoRecipeFound(RecipeImportError):
    pass
