"""Очередь заданий в памяти для тестов и локального запуска. Контракт — jobs/ports.py."""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from jobs.ports import DONE, ERR_JOB_FAILED, FAILED, RUNNING, WAITING, Job


@dataclass
class JobRow:
    """Строка таблицы jobs."""

    id: str
    couple_id: str
    kind: str
    created_at: datetime
    params: dict[str, Any] = field(default_factory=dict)
    status: str = WAITING
    result: dict[str, Any] | None = None
    error: str | None = None
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None


class MemoryJobQueue:
    def __init__(self) -> None:
        self.rows: dict[str, JobRow] = {}
        self._lock = threading.Lock()
        self._next = 1

    def add(
        self, couple_id: str, kind: str, params: Mapping[str, Any], created_at: datetime
    ) -> str:
        """Так задание ставит Go-бэкенд (`EnqueueJob`)."""
        with self._lock:
            job_id = str(self._next)
            self._next += 1
            self.rows[job_id] = JobRow(job_id, couple_id, kind, created_at, dict(params))
            return job_id

    def claim(self, kinds: Sequence[str], now: datetime) -> Job | None:
        with self._lock:
            waiting = [r for r in self.rows.values() if r.status == WAITING and r.kind in kinds]
            if not waiting:
                return None
            row = min(waiting, key=lambda r: (r.created_at, int(r.id)))
            row.status, row.started_at, row.attempts = RUNNING, now, row.attempts + 1
            return Job(row.id, row.couple_id, row.kind, dict(row.params), row.attempts)

    def complete(self, job_id: str, result: Mapping[str, Any], now: datetime) -> None:
        with self._lock:
            row = self._running(job_id)
            row.status, row.result, row.finished_at = DONE, dict(result), now

    def fail(self, job_id: str, code: str, message: str, now: datetime) -> None:
        with self._lock:
            self._fail(self._running(job_id), code, message, now)

    def release_stale(self, started_before: datetime, max_attempts: int, now: datetime) -> int:
        with self._lock:
            stale = [
                r
                for r in self.rows.values()
                if r.status == RUNNING
                and r.started_at is not None
                and r.started_at < started_before
            ]
            for row in stale:
                if row.attempts >= max_attempts:
                    message = f"воркер не завершил задание за {row.attempts} попытки"
                    self._fail(row, ERR_JOB_FAILED, message, now)
                else:
                    row.status, row.started_at = WAITING, None
            return len(stale)

    def _running(self, job_id: str) -> JobRow:
        row = self.rows.get(job_id)
        if row is None or row.status != RUNNING:
            raise KeyError(f"задание {job_id} не выполняется")
        return row

    @staticmethod
    def _fail(row: JobRow, code: str, message: str, now: datetime) -> None:
        row.status, row.error, row.finished_at = FAILED, message, now
        row.result = {"error": {"code": code, "message": message}}
