"""Цикл воркера: взять задание, выполнить, записать итог. Падение обработчика не роняет цикл."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from jobs.handlers import Handler
from jobs.ports import ERR_INTERNAL, JobFailure, JobQueue

log = logging.getLogger("jobs")

STALE_AFTER = timedelta(minutes=10)  # импорт укладывается в минуты; дольше — воркер упал
MAX_ATTEMPTS = 3
POLL_S = 5.0


@dataclass
class Worker:
    queue: JobQueue
    handlers: Mapping[str, Handler]
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    stale_after: timedelta = STALE_AFTER
    max_attempts: int = MAX_ATTEMPTS

    def run_once(self) -> bool:
        """Выполняет одно задание. False — брать нечего."""
        job = self.queue.claim(list(self.handlers), self.clock())
        if job is None:
            return False
        log.info("задание %s (%s), попытка %s", job.id, job.kind, job.attempts)
        try:
            result = self.handlers[job.kind](job.params)
        except JobFailure as e:
            log.info("задание %s: %s: %s", job.id, e.code, e.message)
            self.queue.fail(job.id, e.code, e.message, self.clock())
        except Exception as e:  # ошибка в коде обработчика: задание в «ошибка», цикл живёт
            log.exception("задание %s упало", job.id)
            self.queue.fail(job.id, ERR_INTERNAL, f"{type(e).__name__}: {e}", self.clock())
        else:
            self.queue.complete(job.id, result, self.clock())
        return True

    def release_stale(self) -> int:
        now = self.clock()
        released = self.queue.release_stale(now - self.stale_after, self.max_attempts, now)
        if released:
            log.warning("зависших заданий: %s", released)
        return released

    def run(
        self,
        *,
        should_stop: Callable[[], bool] = lambda: False,
        poll_s: float = POLL_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> int:
        """Работает, пока `should_stop()` не вернёт True. Возвращает число выполненных заданий."""
        done = 0
        while not should_stop():
            self.release_stale()
            while not should_stop() and self.run_once():
                done += 1
            if not should_stop():
                sleep(poll_s)
        return done
