"""Контрактные проверки очереди заданий: одни и те же для фейка в памяти и для Postgres.

Реализация на Postgres подключает их так же, как tests/jobs/test_memory_queue.py:

    from jobs.contract import CHECKS, Harness
    @pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
    def test_contract(check):
        check(Harness(make_queue(), add=..., row=...))

`add` ставит задание (как Go `EnqueueJob`), `row` читает строку для проверки
(`status`, `result`, `error`, `attempts`, `started_at`, `finished_at`).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from jobs.ports import DONE, ERR_IMPORT, ERR_JOB_FAILED, FAILED, RUNNING, WAITING, JobQueue

T0 = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


@dataclass
class Harness:
    queue: JobQueue
    add: Callable[[str, str, Mapping[str, Any], datetime], str]
    row: Callable[[str], Mapping[str, Any]]


def _fails(fn: Callable[[], object]) -> bool:
    try:
        fn()
    except Exception:
        return True
    return False  # pragma: no cover - срабатывает, только если реализация нарушает контракт


def check_empty_queue_gives_nothing(h: Harness) -> None:
    assert h.queue.claim(["import"], T0) is None


def check_claims_oldest_waiting_of_requested_kind(h: Harness) -> None:
    quote = h.add("c1", "quote", {}, T0)
    second = h.add("c1", "import", {"url": "https://b.test"}, T0 + timedelta(seconds=2))
    first = h.add("c2", "import", {"url": "https://a.test"}, T0 + timedelta(seconds=1))
    job = h.queue.claim(["import"], T0 + timedelta(minutes=1))
    assert job is not None and job.id == first
    assert (job.couple_id, job.kind, dict(job.params), job.attempts) == (
        "c2",
        "import",
        {"url": "https://a.test"},
        1,
    )
    row = h.row(first)
    assert row["status"] == RUNNING and row["started_at"] == T0 + timedelta(minutes=1)
    assert h.row(second)["status"] == WAITING and h.row(quote)["status"] == WAITING


def check_job_is_claimed_once(h: Harness) -> None:
    h.add("c1", "import", {}, T0)
    assert h.queue.claim(["import"], T0) is not None
    assert h.queue.claim(["import"], T0) is None


def check_parallel_workers_never_share_a_job(h: Harness) -> None:
    ids = {h.add("c1", "import", {}, T0 + timedelta(seconds=i)) for i in range(20)}
    taken: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        while (job := h.queue.claim(["import"], T0)) is not None:
            with lock:
                taken.append(job.id)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(taken) == sorted(ids)  # каждое ровно один раз


def check_complete_stores_result(h: Harness) -> None:
    job_id = h.add("c1", "import", {}, T0)
    h.queue.claim(["import"], T0)
    h.queue.complete(job_id, {"recipe": {"title": "Борщ"}}, T0 + timedelta(seconds=5))
    row = h.row(job_id)
    assert row["status"] == DONE and row["result"] == {"recipe": {"title": "Борщ"}}
    assert row["finished_at"] == T0 + timedelta(seconds=5) and row["error"] is None


def check_fail_stores_code_and_message(h: Harness) -> None:
    job_id = h.add("c1", "import", {}, T0)
    h.queue.claim(["import"], T0)
    h.queue.fail(job_id, ERR_IMPORT, "на странице нет рецепта", T0 + timedelta(seconds=5))
    row = h.row(job_id)
    assert row["status"] == FAILED and row["error"] == "на странице нет рецепта"
    assert row["result"] == {"error": {"code": ERR_IMPORT, "message": "на странице нет рецепта"}}
    assert row["finished_at"] == T0 + timedelta(seconds=5)


def check_only_running_jobs_can_be_finished(h: Harness) -> None:
    job_id = h.add("c1", "import", {}, T0)
    assert _fails(lambda: h.queue.complete(job_id, {}, T0))  # ещё ждёт
    assert _fails(lambda: h.queue.fail("нет-такого", ERR_IMPORT, "x", T0))
    h.queue.claim(["import"], T0)
    h.queue.complete(job_id, {}, T0)
    assert _fails(lambda: h.queue.fail(job_id, ERR_IMPORT, "x", T0))  # уже готово


def check_stale_jobs_go_back_to_waiting(h: Harness) -> None:
    old = h.add("c1", "import", {}, T0)
    fresh = h.add("c1", "import", {}, T0 + timedelta(seconds=1))
    h.queue.claim(["import"], T0)
    h.queue.claim(["import"], T0 + timedelta(minutes=9))
    assert h.queue.release_stale(T0 + timedelta(minutes=5), 3, T0 + timedelta(minutes=10)) == 1
    assert h.row(old)["status"] == WAITING and h.row(fresh)["status"] == RUNNING
    again = h.queue.claim(["import"], T0 + timedelta(minutes=11))
    assert again is not None and again.id == old and again.attempts == 2


def check_stale_job_out_of_attempts_fails(h: Harness) -> None:
    job_id = h.add("c1", "import", {}, T0)
    for i in range(2):
        h.queue.claim(["import"], T0 + timedelta(hours=i))
        h.queue.release_stale(
            T0 + timedelta(hours=i, minutes=1), 2, T0 + timedelta(hours=i, minutes=2)
        )
    row = h.row(job_id)
    assert row["status"] == FAILED and row["attempts"] == 2
    assert row["result"]["error"]["code"] == ERR_JOB_FAILED


CHECKS: tuple[Callable[[Harness], None], ...] = (
    check_empty_queue_gives_nothing,
    check_claims_oldest_waiting_of_requested_kind,
    check_job_is_claimed_once,
    check_parallel_workers_never_share_a_job,
    check_complete_stores_result,
    check_fail_stores_code_and_message,
    check_only_running_jobs_can_be_finished,
    check_stale_jobs_go_back_to_waiting,
    check_stale_job_out_of_attempts_fails,
)
