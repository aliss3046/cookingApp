# jobs/ — воркер заданий

Go-бэкенд ставит задание строкой в таблицу `jobs` и отвечает клиенту `202 + job_id`. Воркер забирает
задание, выполняет и пишет итог в ту же строку. Клиент узнаёт результат через `GET /jobs/{id}` или Realtime.
Прямых вызовов между Go и Python нет ([ADR-0006](../docs/adr/0006-go-api-python-workers.md)).

```
Go: POST /recipes/import ──► jobs: ждёт, params={"url"}
                                  │  claim (атомарно, SKIP LOCKED)
                                  ▼
Python-воркер ──► выполняется ──► обработчик по kind ──► готово + result
                                                     └─► ошибка + {"error": {code, message}}
```

| Файл | Что |
|---|---|
| `ports.py` | порт `JobQueue` (claim, complete, fail, release_stale), статусы, коды ошибок |
| `memory.py` | очередь в памяти для тестов и локального прогона |
| `contract.py` | контрактные проверки: одни и те же для памяти и для Postgres |
| `handlers.py` | обработчики по виду задания |
| `runner.py` | цикл `Worker`: берёт, выполняет, пишет итог, подбирает зависшие |

## Виды заданий

| `kind` | params | result при успехе | Статус |
|---|---|---|---|
| `import` | `{"url": "https://…"}` | `{"recipe": RecipeInput (status=draft), "review": [...], "warnings": [...], "summary": {...}}` — то же, что `python -m importers` | готово |
| `quote` | — | — | **не берётся**: подбор цен корзины ещё не подключён, задание остаётся `ждёт` |

Ингредиенты в черновике указаны кодом справочника (`ingredients.code`, например `onion`). Рецепт в
`recipes` воркер не пишет: черновик проверяет пара, сохраняет бэкенд.

## Ошибки

| Случай | Итог | `code` |
|---|---|---|
| нет ссылки в params | ошибка | `validation_failed` |
| страница не открылась, нет рецепта, запрет robots.txt | ошибка | `import_failed` |
| баг в обработчике | ошибка, цикл продолжает работу | `internal` |
| воркер упал посреди задания | через 10 минут снова `ждёт`; после 3 попыток ошибка | `job_failed` |

При ошибке: `jobs.error` — текст для человека, `jobs.result` — `{"error": {"code", "message"}}`
в формате `Error` из OpenAPI. Повтор после `validation_failed` и `import_failed` не делается: он не поможет.

## Запуск

Локально, без базы (очередь в памяти):

```bash
python -m jobs import https://example.com/recipe
```

В работе воркер создаётся с очередью на Postgres (её пишет разработчик БД) и крутится в цикле:

```python
from importers.directory import load_directory
from jobs.handlers import default_handlers
from jobs.runner import Worker

Worker(PostgresJobQueue(conn), default_handlers(load_directory())).run()
```

## Для разработчика БД: Postgres-реализация порта

Колонки `started_at` и `attempts` добавляет миграция `0002_jobs_attempts.sql`. Образцы SQL ниже проверены
на Postgres 17 в [db/migrations/checks/0002_jobs_queue_checks.sql](../db/migrations/checks/0002_jobs_queue_checks.sql).

```sql
-- claim(kinds, now)
UPDATE jobs SET status = 'выполняется', started_at = :now, attempts = attempts + 1
WHERE id = (
    SELECT id FROM jobs
    WHERE status = 'ждёт' AND kind = ANY (:kinds)
    ORDER BY created_at, id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING id, couple_id, kind, params, attempts;

-- complete(job_id, result, now): если строк 0 — задание не выполняется, это ошибка
UPDATE jobs SET status = 'готово', result = :result, finished_at = :now
WHERE id = :job_id AND status = 'выполняется';

-- fail(job_id, code, message, now)
UPDATE jobs SET status = 'ошибка', error = :message, finished_at = :now,
       result = jsonb_build_object('error', jsonb_build_object('code', :code, 'message', :message))
WHERE id = :job_id AND status = 'выполняется';

-- release_stale(started_before, max_attempts, now) — см. файл проверок
```

Реализация подключает общие проверки, как `tests/jobs/test_memory_queue.py`:

```python
from jobs.contract import CHECKS, Harness

@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
def test_postgres_queue(check, pg):
    check(Harness(PostgresJobQueue(pg), add=insert_job, row=read_job))
```

`release_stale` и `claim` выполняются воркером в отдельных транзакциях; `SKIP LOCKED` позволяет
запускать несколько воркеров одновременно.
