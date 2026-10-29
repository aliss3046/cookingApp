-- Проверка образцов SQL очереди заданий из jobs/README.md на настоящем Postgres.
-- Запуск после всех миграций; всё откатывается. Номера строк не используются:
-- identity не откатывается вместе с транзакцией, задания различаются по params.

BEGIN;

CREATE TEMP TABLE c AS WITH x AS (INSERT INTO couples (name) VALUES ('Иван и Алиса') RETURNING couple_id)
SELECT couple_id FROM x;

INSERT INTO jobs (couple_id, kind, params, created_at)
SELECT couple_id, kind, params::jsonb, created_at::timestamptz FROM c, (VALUES
    ('quote',  '{"n": "q"}',              '2026-10-25 12:00:00+00'),
    ('import', '{"url": "https://b.test"}', '2026-10-25 12:00:02+00'),
    ('import', '{"url": "https://a.test"}', '2026-10-25 12:00:01+00')
) v (kind, params, created_at);

-- claim: самое старое «ждёт» нужного вида, атомарно (два воркера одно задание не возьмут).
UPDATE jobs SET status = 'выполняется', started_at = '2026-10-25 12:01:00+00', attempts = attempts + 1
WHERE id = (
    SELECT id FROM jobs
    WHERE status = 'ждёт' AND kind = ANY (ARRAY['import'])
    ORDER BY created_at, id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING id, couple_id, kind, params, attempts;

DO $$ BEGIN
    IF (SELECT params->>'url' FROM jobs WHERE status = 'выполняется') <> 'https://a.test' THEN
        RAISE EXCEPTION 'взято не самое старое задание';
    END IF;
END $$;

-- complete
UPDATE jobs SET status = 'готово', result = '{"recipe": {"title": "Борщ"}}', finished_at = now()
WHERE params->>'url' = 'https://a.test' AND status = 'выполняется';

-- Второе задание импорта взял воркер, который потом упал.
UPDATE jobs SET status = 'выполняется', started_at = '2026-10-25 11:00:00+00', attempts = attempts + 1
WHERE params->>'url' = 'https://b.test';

-- release_stale: зависшие дольше порога; исчерпавшие попытки — в ошибку, остальные снова ждут.
WITH stale AS (
    SELECT id, attempts FROM jobs
    WHERE status = 'выполняется' AND started_at < '2026-10-25 11:50:00+00'
    FOR UPDATE SKIP LOCKED
)
UPDATE jobs j SET
    status      = CASE WHEN s.attempts >= 3 THEN 'ошибка' ELSE 'ждёт' END,
    started_at  = CASE WHEN s.attempts >= 3 THEN j.started_at END,
    finished_at = CASE WHEN s.attempts >= 3 THEN now() END,
    error       = CASE WHEN s.attempts >= 3 THEN 'воркер не завершил задание' END,
    result      = CASE WHEN s.attempts >= 3
                       THEN '{"error": {"code": "job_failed", "message": "воркер не завершил задание"}}'::jsonb END
FROM stale s WHERE j.id = s.id;

DO $$ BEGIN
    IF (SELECT status FROM jobs WHERE params->>'url' = 'https://b.test') <> 'ждёт'
       OR (SELECT attempts FROM jobs WHERE params->>'url' = 'https://b.test') <> 1 THEN
        RAISE EXCEPTION 'зависшее задание должно вернуться в очередь';
    END IF;
    IF (SELECT status FROM jobs WHERE kind = 'quote') <> 'ждёт' THEN RAISE EXCEPTION 'quote не трогаем'; END IF;
    IF (SELECT status FROM jobs WHERE params->>'url' = 'https://a.test') <> 'готово' THEN
        RAISE EXCEPTION 'готовое не трогаем';
    END IF;
END $$;

-- «выполняется» без времени начала запрещено.
DO $$ BEGIN
    BEGIN
        UPDATE jobs SET status = 'выполняется', started_at = NULL WHERE kind = 'quote';
        RAISE EXCEPTION 'ожидался отказ: выполняется без started_at';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END $$;

SELECT 'очередь заданий: проверки прошли' AS result;
ROLLBACK;
