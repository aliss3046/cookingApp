# Схема БД (PostgreSQL)

Статус: **черновик на согласование**. Миграции пишутся в Фазе 1 строго по этому документу;
любое изменение схемы сначала попадает сюда.

Общие правила: `id uuid` (default `gen_random_uuid()`), `created_at/updated_at timestamptz`.
Количества только в базовых единицах: `g`, `ml`, `pcs`. Деньги — `numeric(10,2)`, валюта RUB.
Цены только добавляются (INSERT-only), не перезаписываются.

## Пара и доступ

| Таблица | Поля | Заметки |
|---|---|---|
| `couples` | id, name | |
| `couple_members` | couple_id, user_id (→ auth.users), role (`owner`/`partner`) | уникально (couple_id, user_id); не более 2 строк на пару |

## Справочник и рецепты

| Таблица | Поля | Заметки |
|---|---|---|
| `ingredients` | id, name, synonyms text[], group, density_g_per_ml, piece_weight_g, kcal/protein/fat/carbs_per_100g (null, позже), external_ref | поиск по name+synonyms |
| `unit_conversions` | unit_name (ст. ложка, ч. ложка, стакан, щепотка, зубчик, пучок, штука), to_base_qty, base_unit (`g`/`ml`/`pcs`), ingredient_id (null = общая) | «ст. ложка → г» через справочник, не в рецепте |
| `recipes` | id, couple_id (null = общая), title, default_servings, source_url, tags text[], status (`draft`/`confirmed`) | импорт создаёт `draft` |
| `recipe_ingredients` | recipe_id, ingredient_id (null если не разобрано), qty_per_serving, unit (`g`/`ml`/`pcs`), optional bool, raw_text, needs_review bool | неразобранные строки сохраняются с `needs_review = true` и `raw_text` |
| `votes` | recipe_id, user_id, value (`want`/`neutral`/`dont_want`) | уникально (recipe_id, user_id) |

## План, запасы, корзина

| Таблица | Поля | Заметки |
|---|---|---|
| `plans` | id, couple_id, week_start date, status | |
| `plan_items` | id, plan_id, recipe_id, servings, date | |
| `pantry` | couple_id, ingredient_id, qty, unit, source (`manual`/`leftover`) | `leftover` — остаток от упаковок |
| `cart_lines` | id, plan_id, ingredient_id (null для ручной позиции), title, qty, unit, excluded bool, added_manually bool, chosen_product_id | |

## Магазины и цены

| Таблица | Поля | Заметки |
|---|---|---|
| `stores` | id, code (`dixy`/`lenta`/`manual`), name, collection_enabled bool (default false) | сбор включается только после проверки условий использования |
| `store_locations` | id, store_id, couple_id, address, zone, region_key, delivery_fee, free_delivery_from | один адрес пары на старте |
| `products` | id, store_id, external_id, title, pack_qty, pack_unit, category | уникально (store_id, external_id) |
| `ingredient_product_map` | ingredient_id, product_id, preferred bool, confidence numeric(3,2), confirmed_by_couple bool | |
| `prices` | id, product_id, location_id, price, card_price, price_per_kg, in_stock, store_only, fetched_at, source (`site`/`manual`/`receipt`) | INSERT-only; индекс (product_id, location_id, fetched_at desc) |
| `jobs` | id, couple_id, kind (`quote`/`import`), status, params jsonb, result jsonb, error, created_at, finished_at | |

Устаревание цены вычисляется на чтении: `now() - fetched_at > 3 days` → `stale = true`.

## RLS (набросок)

- Таблицы пары (`recipes` с `couple_id`, `plans`, `plan_items`, `pantry`, `cart_lines`,
  `store_locations`, `jobs`): доступ, если `exists (select 1 from couple_members where couple_id = row.couple_id and user_id = auth.uid())`. Для таблиц без своего `couple_id` — через `plan_id`.
- Общие `recipes` (`couple_id is null`), `ingredients`, `unit_conversions`, `stores`, `products`,
  `prices`, `ingredient_product_map`: чтение для авторизованных, запись только сервисной ролью.
- `votes`: читают оба в паре, пишет только свой `user_id`.

## Задел под будущее

КБЖУ-поля в `ingredients` уже есть. Для масштабирования: все пользовательские таблицы
привязаны к `couple_id`, внешние ключи индексированы, `prices` можно партиционировать по `fetched_at`.
