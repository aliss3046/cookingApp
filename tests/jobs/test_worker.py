import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import jobs.__main__ as cli
from importers.directory import load_directory
from importers.errors import FetchFailed
from jobs.handlers import default_handlers, import_recipe
from jobs.memory import MemoryJobQueue
from jobs.ports import (
    DONE,
    ERR_IMPORT,
    ERR_INTERNAL,
    ERR_JOB_FAILED,
    ERR_VALIDATION,
    FAILED,
    RUNNING,
    WAITING,
    JobFailure,
)
from jobs.runner import Worker

PAGES = Path(__file__).parents[1] / "importers" / "fixtures" / "pages"
T0 = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
URL = "https://recipes.test/borsch"


@pytest.fixture(scope="module")
def directory():
    return load_directory()


def page(name: str) -> str:
    return (PAGES / name).read_text(encoding="utf-8")


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def worker(queue, directory, fetch, **kw) -> Worker:
    return Worker(queue, default_handlers(directory, fetch=fetch), clock=Clock(), **kw)


def test_import_job_produces_recipe_draft(directory):
    q = MemoryJobQueue()
    job_id = q.add("c1", "import", {"url": URL}, T0)
    fetched = []

    def fetch(url):
        fetched.append(url)
        return page("plain_recipe.html")

    assert worker(q, directory, fetch).run_once() is True
    row = q.rows[job_id]
    assert fetched == [URL] and row.status == DONE and row.error is None
    recipe = row.result["recipe"]
    assert recipe["status"] == "draft" and recipe["source_url"] == URL and recipe["ingredients"]
    assert set(row.result) == {"recipe", "review", "warnings", "summary"}


@pytest.mark.parametrize(
    ("params", "code"),
    [({}, ERR_VALIDATION), ({"url": "  "}, ERR_VALIDATION), ({"url": 5}, ERR_VALIDATION)],
)
def test_import_without_url_fails_validation(directory, params, code):
    q = MemoryJobQueue()
    job_id = q.add("c1", "import", params, T0)
    worker(q, directory, lambda u: pytest.fail("сеть не нужна")).run_once()
    assert q.rows[job_id].status == FAILED
    assert q.rows[job_id].result["error"]["code"] == code


def test_page_without_recipe_and_fetch_errors_fail_as_import(directory):
    q = MemoryJobQueue()
    no_recipe = q.add("c1", "import", {"url": URL}, T0)
    broken = q.add("c1", "import", {"url": URL + "2"}, T0 + timedelta(seconds=1))

    def fetch(url):
        if url.endswith("2"):
            raise FetchFailed("HTTP 503")
        return page("no_recipe.html")

    w = worker(q, directory, fetch)
    assert w.run_once() and w.run_once()
    assert q.rows[no_recipe].result["error"]["code"] == ERR_IMPORT
    assert q.rows[broken].error == "HTTP 503"


def test_import_error_without_text_uses_class_name(directory):
    def fetch(url):
        raise FetchFailed()

    with pytest.raises(JobFailure) as e:
        import_recipe({"url": URL}, directory=directory, fetch=fetch)
    assert (e.value.code, e.value.message) == (ERR_IMPORT, "FetchFailed")


def test_bug_in_handler_fails_job_but_worker_goes_on():
    q = MemoryJobQueue()
    bad = q.add("c1", "import", {}, T0)
    good = q.add("c1", "import", {}, T0 + timedelta(seconds=1))
    calls = []

    def handler(params):
        calls.append(params)
        if len(calls) == 1:
            raise ZeroDivisionError("деление на ноль")
        return {"ok": True}

    w = Worker(q, {"import": handler}, clock=Clock())
    assert w.run_once() and w.run_once() and not w.run_once()
    assert q.rows[bad].result["error"] == {
        "code": ERR_INTERNAL,
        "message": "ZeroDivisionError: деление на ноль",
    }
    assert q.rows[good].status == DONE and q.rows[good].result == {"ok": True}


def test_unknown_kinds_stay_waiting(directory):
    q = MemoryJobQueue()
    quote = q.add("c1", "quote", {}, T0)
    assert worker(q, directory, lambda u: "").run_once() is False
    assert q.rows[quote].status == WAITING  # цены корзины воркер пока не берёт


def test_run_loop_releases_stale_jobs_and_stops(directory):
    q = MemoryJobQueue()
    lost = q.add("c1", "import", {"url": URL}, T0)
    q.claim(["import"], T0 - timedelta(hours=1))  # воркер упал час назад
    fresh = q.add("c1", "import", {"url": URL}, T0 + timedelta(seconds=1))
    sleeps = []
    w = worker(q, directory, lambda u: page("plain_recipe.html"))
    done = w.run(should_stop=lambda: len(sleeps) >= 2, poll_s=0.5, sleep=sleeps.append)
    assert done == 2 and sleeps == [0.5, 0.5]
    assert q.rows[lost].status == DONE and q.rows[lost].attempts == 2
    assert q.rows[fresh].status == DONE


def test_stale_job_out_of_attempts_is_failed(directory):
    q = MemoryJobQueue()
    job_id = q.add("c1", "import", {}, T0)
    q.claim(["import"], T0 - timedelta(hours=1))
    w = worker(q, directory, lambda u: "", max_attempts=1)
    assert w.release_stale() == 1
    assert q.rows[job_id].result["error"]["code"] == ERR_JOB_FAILED
    assert w.release_stale() == 0


def test_run_stops_before_and_between_jobs(directory):
    q = MemoryJobQueue()
    q.add("c1", "import", {}, T0)
    assert worker(q, directory, lambda u: "").run(should_stop=lambda: True) == 0
    flags = iter([False, True])
    w = worker(q, directory, lambda u: "")
    assert w.run(should_stop=lambda: next(flags, True), sleep=lambda s: None) == 0
    assert next(iter(q.rows.values())).status == WAITING


def test_stop_right_after_a_job_skips_sleep(directory):
    q = MemoryJobQueue()
    q.add("c1", "import", {}, T0)
    flags = iter([False, False, True])
    w = worker(q, directory, lambda u: "")
    assert w.run(should_stop=lambda: next(flags, True), sleep=pytest.fail) == 1


def test_running_job_is_left_alone_until_stale(directory):
    q = MemoryJobQueue()
    job_id = q.add("c1", "import", {}, T0)
    q.claim(["import"], T0 + timedelta(seconds=30))
    assert worker(q, directory, lambda u: "").release_stale() == 0
    assert q.rows[job_id].status == RUNNING


def run_cli(**kw):
    out = io.StringIO()
    return cli.main(["import", URL], out=out, **kw), out.getvalue()


def test_cli_runs_one_import(directory):
    code, out = run_cli(fetch=lambda u: page("plain_recipe.html"), directory=directory)
    assert code == cli.EXIT_OK and '"status": "готово"' in out and URL in out


def test_cli_reports_failure(directory):
    code, out = run_cli(fetch=lambda u: page("no_recipe.html"), directory=directory)
    assert code == cli.EXIT_FAILED and "import_failed" in out


def test_cli_loads_directory_by_default(monkeypatch, directory):
    monkeypatch.setattr(cli, "load_directory", lambda: directory)
    assert run_cli(fetch=lambda u: page("plain_recipe.html"))[0] == cli.EXIT_OK
