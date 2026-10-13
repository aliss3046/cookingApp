"""Профили магазинов: что и как читать. Магазин включается только с явной записью об одобрении."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from prices.politeness import MAX_DAILY_LIMIT, MIN_DELAY_FLOOR_S

DEFAULT_PATH: Final = Path(__file__).resolve().parent / "stores.json"


class ProfileError(ValueError):
    pass


class StoreDisabled(Exception):
    """Магнит или другой магазин не включён владельцем проекта: сбор запрещён."""


@dataclass(frozen=True)
class Approval:
    by: str  # кто принял решение
    on: str  # когда (ГГГГ-ММ-ДД)
    basis: str  # на каком основании


@dataclass(frozen=True)
class CategorySpec:
    url: str
    groups: tuple[str, ...] = ()  # группы справочника, чьи ингредиенты тут ищем
    ingredients: tuple[str, ...] = ()  # или конкретные ингредиенты
    note: str = ""


@dataclass(frozen=True)
class StoreProfile:
    code: str
    name: str
    enabled: bool
    approval: Approval | None
    base_url: str
    min_delay_s: float
    daily_request_limit: int
    categories: tuple[CategorySpec, ...]
    notes: str = ""

    def require_enabled(self) -> None:
        if not self.enabled:
            raise StoreDisabled(
                f"магазин «{self.code}» выключен: включает владелец проекта (docs/stores.md)"
            )


def _parse_category(store: str, base_host: str, raw: dict[str, Any]) -> CategorySpec:
    url = raw.get("url", "")
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != base_host:
        raise ProfileError(f"{store}: адрес категории должен быть https и на {base_host}: {url!r}")
    if not raw.get("groups") and not raw.get("ingredients"):
        raise ProfileError(f"{store}: у категории {url} не указаны ни группы, ни ингредиенты")
    return CategorySpec(
        url=url,
        groups=tuple(raw.get("groups", ())),
        ingredients=tuple(raw.get("ingredients", ())),
        note=raw.get("note", ""),
    )


def parse_profile(code: str, raw: dict[str, Any]) -> StoreProfile:
    base_url = raw["base_url"]
    parts = urlsplit(base_url)
    if parts.scheme != "https" or not parts.netloc:
        raise ProfileError(f"{code}: base_url должен быть https-адресом: {base_url!r}")

    delay = float(raw.get("min_delay_s", MIN_DELAY_FLOOR_S))
    if delay < MIN_DELAY_FLOOR_S:
        raise ProfileError(f"{code}: пауза {delay} с меньше минимума {MIN_DELAY_FLOOR_S} с")
    limit = int(raw.get("daily_request_limit", 100))
    if not 1 <= limit <= MAX_DAILY_LIMIT:
        raise ProfileError(f"{code}: суточный лимит должен быть от 1 до {MAX_DAILY_LIMIT}")

    approval = None
    if raw.get("approval"):
        a = raw["approval"]
        if not all(a.get(k) for k in ("by", "on", "basis")):
            raise ProfileError(f"{code}: approval требует by, on и basis")
        approval = Approval(by=a["by"], on=a["on"], basis=a["basis"])
    enabled = bool(raw.get("enabled", False))
    if enabled and approval is None:
        raise ProfileError(
            f"{code}: магазин включён без записи approval (кто, когда, на каком основании)"
        )

    return StoreProfile(
        code=code,
        name=raw.get("name", code),
        enabled=enabled,
        approval=approval,
        base_url=base_url,
        min_delay_s=delay,
        daily_request_limit=limit,
        categories=tuple(_parse_category(code, parts.netloc, c) for c in raw.get("categories", ())),
        notes=raw.get("notes", ""),
    )


def load_profiles(path: Path = DEFAULT_PATH) -> dict[str, StoreProfile]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: parse_profile(k, v) for k, v in data.items() if not k.startswith("_")}
