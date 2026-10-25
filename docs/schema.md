# Схема БД (PostgreSQL)

Статус: **принята**. Основа — схема разработчика БД (`cooking.sql`, дамп от 16.10.2026). Исполняемая версия —
миграция [db/migrations/0001_init.sql](../db/migrations/0001_init.sql), проверки на примерах —
[db/migrations/checks/0001_init_checks.sql](../db/migrations/checks/0001_init_checks.sql).
Любое изменение схемы делается новой миграцией и сразу отражается здесь.
Подробное описание каждой таблицы: [db-tables.md](db-tables.md).

Общие правила:
- Первичные ключи `integer GENERATED ALWAYS AS IDENTITY` (`prices.id` — `bigint`). Ключ таблицы назван
  `<сущность>_id` (`couple_id`, `recipe_id`, `plan_id`, `store_id`, `ingredient_id`) или `id`.
  Внешний ключ называется так же, как ключ, на который ссылается.
- В API идентификаторы передаются строкой (`domain.ID`), адаптер переводит их в `integer`.
- У ингредиента, кроме числового ключа, есть стабильный код `code` (`onion`, `milk`): по нему работают сиды
  и Python-часть (импорт, подбор товаров).
- Количества только в базовых единицах: `g`, `ml`, `pcs`. Деньги — `numeric(10,2)`, валюта RUB.
- Время — `timestamptz`.
- Цены только добавляются (INSERT-only), не перезаписываются.
- Удаление пары удаляет её данные (`ON DELETE CASCADE`); общие рецепты и справочники остаются.

## Пара и доступ

| Таблица | Поля | Заметки |
|---|---|---|
| `couples` | couple_id, name, created_at | |
| `couple_members` | couple_id, user_id (→ auth.users), role (`owner`/`partner`) | ключ (couple_id, user_id); не более 2 строк на пару (триггер) |

## Справочник и рецепты

| Таблица | Поля | Заметки |
|---|---|---|
| `ingredients` | ingredient_id, code, name, synonyms text[], ingredient_group, density_g_per_ml, piece_weight_g | `code` уникален |
| `recipes` | recipe_id, couple_id (null — общее блюдо), title, default_servings (по умолчанию 2), source_url, tags text[], status (`draft`/`active`) | импорт создаёт `draft`; в голосовании и плане только `active` |
| `recipe_ingredients` | id, recipe_id, ingredient_id (null, если не разобрано), per_serving (null, если не разобрано), unit (`g`/`ml`/`pcs`), optional, raw_text, needs_review | без ингредиента или количества строка обязана иметь `needs_review = true` |
| `votes` | recipe_id, couple_id, user_id, value (`want`/`neutral`/`dont_want`) | ключ (recipe_id, user_id); (couple_id, user_id) → couple_members: голосует только участник пары |

## План, запасы, корзина

| Таблица | Поля | Заметки |
|---|---|---|
| `plan` | plan_id, couple_id, week_start date (понедельник), status (`draft`/`confirmed`) | одна неделя на пару: уникально (couple_id, week_start) |
| `plan_items` | id, plan_id, recipe_id, servings, date (null — на неделю), meal (`breakfast`/`lunch`/`dinner`/`snack`, null) | `servings >= 1`; `meal` только вместе с `date`; `date` внутри недели плана проверяет бэкенд (`PlanItem.Validate`); в день и приём пищи можно несколько блюд |
| `pantry` | couple_id, ingredient_id, qty, unit, source (`manual`/`leftover`) | ключ (couple_id, ingredient_id, unit, source); `leftover` — остаток от упаковок |
| `cart_lines` | id, plan_id, ingredient_id (null для ручной позиции), title, qty, unit, excluded, added_manually, qty_overridden, chosen_product_id (→ products) | без ингредиента только ручная позиция; `qty_overridden` — пара сама задала количество; `chosen_product_id` — закреплённый товар |

## Магазины и цены

| Таблица | Поля | Заметки |
|---|---|---|
| `stores` | store_id, code (`dixy`/`magnit`/`manual`), name, collection_price | `code` уникален; `collection_price` — сбор цен включён (по умолчанию false) |
| `store_location` | id, store_id, couple_id, address, region_key, delivery_fee, free_delivery_from | `region_key` у Магнита — `shopCode` |
| `products` | id, store_id, external_id, title, brand, sale_mode (`pack_mass`/`pack_count`/`per_piece`/`by_weight`), pack_qty, pack_unit, category | уникально (store_id, external_id) |
| `ingredient_product_map` | ingredient_id, product_id, preferred, confidence numeric(3,2) 0..1, confirmed_by_couple, matcher_version | ключ (ingredient_id, product_id) |
| `prices` | id, product_id, location_id (→ store_location), price, card_price, price_per_kg, in_stock, store_only, fetched_at, source (`site`/`manual`/`receipt`) | INSERT-only; индекс (product_id, location_id, fetched_at desc) |
| `jobs` | id, couple_id, kind (`import`/`quote`), status (`ждёт`/`выполняется`/`готово`/`ошибка`), params jsonb, result jsonb, error, created_at, finished_at | новое задание `ждёт`; индекс по ждущим |

Устаревание цены вычисляется на чтении: `now() - fetched_at > 3 days` → `stale = true`.

## Отличия от `cooking.sql`

Структура и имена разработчика сохранены: `plan`, `store_location`, целые ключи, статус рецепта `active`,
русские статусы заданий, `collection_price`. Изменено только то, что ломает логику или код. Код (Go, OpenAPI,
сиды) приведён к этим значениям: статус рецепта `confirmed` → `active`, статусы заданий
`queued/running/done/failed` → `ждёт/выполняется/готово/ошибка`.

**Опечатки и единые имена**

| Было | Стало | Почему |
|---|---|---|
| `ingredients.ingredint_id` | `ingredient_id` | опечатка |
| `store_location.adress` | `address` | опечатка |
| `couples.couples_id`, `plan.couples_id`, `recipes.couples_id` | `couple_id` | в остальных таблицах уже `couple_id`; одно имя — меньше ошибок в запросах |
| `recipes.recipes_id`, `recipe_ingredients.recipes_id`, `votes.recipes_id` | `recipe_id` | в `plan_items` уже `recipe_id` |

**Логические ошибки**

| Где | Было | Стало | Что ломалось |
|---|---|---|---|
| `recipes.couples_id` | NOT NULL | может быть NULL | общие блюда (42 стартовых) некуда положить |
| `recipe_ingredients.ingredient_id`, `per_serving` | NOT NULL | NULL при `needs_review` | неразобранную строку импорта нельзя сохранить, рецепт терялся |
| `cart_lines.ingredient_id` | NOT NULL | NULL для ручной позиции | нельзя добавить в корзину «салфетки» |
| `votes.value` | по умолчанию `'dont want'`, значение с пробелом | без значения по умолчанию, `dont_want` | голос «не хочу» появлялся сам; значение расходилось с API |
| `jobs.status` | по умолчанию `выполняется` | по умолчанию `ждёт` | воркер не находил новые задания |
| `jobs` | нет `params`, `result` | `params jsonb`, `result jsonb` | заданию нечего передать (ссылку) и некуда вернуть результат |
| `plan.week_start` | `timestamp`, по умолчанию `now()` | `date`, только понедельник, без значения по умолчанию | неделя начиналась с произвольного момента; две «одинаковые» недели |
| Таблицы без ключа: `votes`, `pantry`, `prices`, `recipe_ingredients`, `ingredient_product_map` | — | первичные ключи | дубли: два голоса одного человека, два запаса молока |
| `couple_members` | роль без проверки, нет лимита | `owner`/`partner`, не больше двух (триггер) | третий участник, роль с опечаткой |
| `stores.code`, `products (store_id, external_id)` | не уникальны | уникальны | повторный сбор цен плодил товары |
| `prices` | `fetched_at` может быть NULL, нет проверки `source` | NOT NULL, по умолчанию `now()`, проверка | цена без даты не может устареть |
| Деньги | `numeric` | `numeric(10,2)`, цена > 0 | |
| Время | `timestamp` без пояса | `timestamptz` | сдвиг времени между сервером и клиентом |

**Добавлено, без чего не работает код**

| Поле | Кто использует |
|---|---|
| `ingredients.code` | сиды, импорт рецептов, подбор товаров (ингредиенты там по коду) |
| `ingredients.synonyms`, `density_g_per_ml` | поиск ингредиента по строке рецепта, перевод мл ↔ г |
| `recipes.source_url`, `tags` | импорт по ссылке; фильтр блюд по метке |
| `plan_items.meal` | приём пищи в плане (`domain.Meal`) |
| `cart_lines.qty_overridden`, `chosen_product_id` | количество, заданное парой; закреплённый товар |
| `products.brand`, `sale_mode`, `pack_qty`, `pack_unit` | расчёт упаковок в корзине, выбор марки |
| `prices.card_price`, `price_per_kg` | цена по карте, сравнение разных упаковок |
| `ingredient_product_map.matcher_version` | подбор пересчитывается при смене правил |
| Индексы по внешним ключам | выборки по паре и последней цене |

Таблицы `unit_conversions` (была в черновике схемы) нет: бытовые меры в граммы переводит импорт рецептов
(`importers/units.py`) до записи в базу.

## RLS (набросок)

- Таблицы пары (`recipes` с `couple_id`, `plan`, `plan_items`, `pantry`, `cart_lines`,
  `store_location`, `jobs`, `votes`): доступ, если `exists (select 1 from couple_members where couple_id = row.couple_id and user_id = auth.uid())`. Для таблиц без своего `couple_id` — через `plan_id` или `recipe_id`.
- Общие `recipes` (`couple_id is null`), `ingredients`, `stores`, `products`, `prices`,
  `ingredient_product_map`: чтение для авторизованных, запись только сервисной ролью.
- `votes`: читают оба в паре, пишет только свой `user_id`.

## Задел под будущее

КБЖУ в `ingredients` пока нет, добавляется отдельной миграцией. Все пользовательские таблицы привязаны
к `couple_id`, внешние ключи индексированы, `prices` можно партиционировать по `fetched_at`.
