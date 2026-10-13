# api/ — Go

HTTP API `/v1`, расчёт корзины, голосование, постановка задач воркерам.
Решение: [ADR-0006](../docs/adr/0006-go-api-python-workers.md).

```
cmd/server/              точка входа (пока только /v1/healthz)
internal/domain/         доменные типы (по docs/openapi.yaml и docs/schema.md)
internal/ports/          интерфейсы репозиториев — договор с разработчиком БД
internal/ports/memory/   фейк в памяти для тестов логики
internal/ports/contracttest/  общие тесты поведения портов
```

## Для разработчика БД

1. Реализуйте интерфейсы из `internal/ports/ports.go` в своём пакете
   (например, `internal/store/postgres`).
2. Подключите контрактные тесты:

   ```go
   func TestContract(t *testing.T) {
       contracttest.Run(t, func(t *testing.T) contracttest.Env {
           // чистая база, две пары, одно общее блюдо
       })
   }
   ```

3. Правила, которые проверяют тесты: `couple_id` передаётся явно, чужие данные пары
   возвращаются как `ports.ErrNotFound`, общие блюда видны всем, но не удаляются.
4. Изменение интерфейса порта — только PR, который видят обе стороны.

## Команды

```
go test ./... -cover
go run ./cmd/server
```
