-- 0002_jobs_attempts: воркер заданий.
-- started_at — когда воркер взял задание; без него не найти задания, брошенные упавшим воркером.
-- attempts — сколько раз брали; ограничивает перезапуск «ядовитого» задания.

BEGIN;

ALTER TABLE jobs
    ADD COLUMN started_at timestamptz,
    ADD COLUMN attempts   integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    ADD CONSTRAINT jobs_running_has_start CHECK (status <> 'выполняется' OR started_at IS NOT NULL);

CREATE INDEX jobs_running_idx ON jobs (started_at) WHERE status = 'выполняется';

COMMIT;
