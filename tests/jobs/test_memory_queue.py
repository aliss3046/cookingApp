import pytest

from jobs.contract import CHECKS, Harness
from jobs.memory import MemoryJobQueue


def harness() -> Harness:
    q = MemoryJobQueue()
    return Harness(q, add=q.add, row=lambda job_id: vars(q.rows[job_id]))


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
def test_memory_queue_meets_contract(check):
    check(harness())
