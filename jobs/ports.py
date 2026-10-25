"""Порт очереди заданий. Реализацию на Postgres пишет разработчик БД (ADR-0006).

Поведение, которое обязана повторить любая реализация, проверяет `jobs.contract`.
Пример SQL для Postgres — в jobs/README.md.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Protocol

# Значения jobs.status в базе (db/migrations/0001_init.sql).
WAITING: Final = "ждёт"
RUNNING: Final = "выполняется"
DONE: Final = "готово"
FAILED: Final = "ошибка"

KIND_IMPORT: Final = "import"
KIND_QUOTE: Final = "quote"

# Коды ошибок совпадают с ErrorCode в docs/openapi.yaml.
ERR_VALIDATION: Final = "validation_failed"
ERR_IMPORT: Final = "import_failed"
ERR_INTERNAL: Final = "internal"
ERR_JOB_FAILED: Final = "job_failed"


@dataclass(frozen=True)
class Job:
    """Задание, которое воркер забрал и выполняет."""

    id: str
    couple_id: str
    kind: str
    params: Mapping[str, Any] = field(default_factory=dict)
    attempts: int = 1  # с учётом текущей


class JobFailure(Exception):
    """Задание не может быть выполнено: повтор не поможет. `code` — ErrorCode из OpenAPI."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class JobQueue(Protocol):
    def claim(self, kinds: Sequence[str], now: datetime) -> Job | None:
        """Атомарно берёт самое старое `ждёт` из `kinds`: статус `выполняется`, started_at = now,
        attempts + 1. Два воркера одно задание не получают. Нечего брать — None."""
        ...

    def complete(self, job_id: str, result: Mapping[str, Any], now: datetime) -> None:
        """`выполняется` → `готово`, result, finished_at."""
        ...

    def fail(self, job_id: str, code: str, message: str, now: datetime) -> None:
        """`выполняется` → `ошибка`: error = message, result = {"error": {"code", "message"}}."""
        ...

    def release_stale(self, started_before: datetime, max_attempts: int, now: datetime) -> int:
        """Задания `выполняется`, начатые раньше `started_before` (воркер упал), возвращает
        в `ждёт`; исчерпавшие `max_attempts` — в `ошибка` с кодом job_failed.
        Возвращает число затронутых."""
        ...
