# db/

| Путь | Что |
|---|---|
| `migrations/NNNN_*.sql` | миграции по порядку; схему руками не меняем, только новой миграцией |
| `migrations/checks/` | проверки схемы на примерах (всё в транзакции, откатывается) |
| `seeds/` | справочник ингредиентов (335) и стартовые блюда (42) |

Описание схемы: [docs/schema.md](../docs/schema.md), по таблицам — [docs/db-tables.md](../docs/db-tables.md).
Основа схемы — дамп разработчика БД `cooking.sql` в корне репозитория; отличия от него перечислены в `schema.md`.

Проверить локально на пустой базе:

```bash
psql -v ON_ERROR_STOP=1 -f db/migrations/0001_init.sql -f db/migrations/checks/0001_init_checks.sql
```

CI (задача «БД (миграции)») делает то же на Postgres 17.
