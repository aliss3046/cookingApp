# Таблицы БД: подробное описание

Подробности к [schema.md](schema.md): смысл каждой таблицы, поля, связи, примеры. Источник правды —
миграция [db/migrations/0001_init.sql](../db/migrations/0001_init.sql); при расхождении верна она.
Основа схемы — дамп разработчика БД (`cooking.sql`), список отличий от него в `schema.md`.

## Общие правила

- Ключи `integer GENERATED ALWAYS AS IDENTITY`, у `prices` — `bigint`. В API идентификаторы передаются строкой.
- Внешний ключ называется так же, как ключ, на который ссылается (`couple_id`, `recipe_id`, `plan_id`).
- Количества только в базовых единицах: `g` (граммы), `ml` (миллилитры), `pcs` (штуки). Граммы и миллилитры считаются одинаково, штуки в граммы не переводятся.
- Деньги `numeric(10,2)`, RUB. Время `timestamptz`.
- Цены только добавляются: новая цена — новая строка, старые остаются историей.
- Все данные пары размечены `couple_id`. Чужие данные отдаются как «не найдено» (`ErrNotFound`). Удаление пары удаляет её данные.

Обозначения: **PK** первичный ключ, **FK** внешний ключ, «обяз.» — NOT NULL.

## Карта связей

```
couples ──< couple_members >── auth.users
   │
   ├──< recipes ──< recipe_ingredients >── ingredients
   │        └──< votes  (couple_id, user_id → couple_members)
   ├──< plan ──< plan_items >── recipes
   │       └──< cart_lines >── ingredients, products
   ├──< pantry >── ingredients
   ├──< store_location >── stores
   └──< jobs

stores ──< products ──< prices >── store_location
ingredients ──< ingredient_product_map >── products
```

`──<` значит «один ко многим».

---

## 1. Пара и доступ

### `couples` — пары

«Корень» данных: одна строка на пару, которая вместе пользуется приложением. На неё через `couple_id` ссылаются план, запасы, корзина, рецепты пары, адреса и задания.

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `couple_id` | integer | PK | |
| `name` | text | да | название для интерфейса: «Иван и Алиса» |
| `created_at` | timestamptz | да, `now()` | когда создана |

### `couple_members` — участники пары

Связывает пару с аккаунтами входа (`auth.users` в Supabase).

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `couple_id` | integer | FK → couples | |
| `user_id` | uuid | да | аккаунт (`auth.users.id`) |
| `role` | text | да | `owner` (создал пару) или `partner` (принял приглашение) |

Ключ (`couple_id`, `user_id`). Триггер не даёт добавить третьего участника.
Пример: `1 + Иван = owner`, `1 + Алиса = partner`.

---

## 2. Справочник и рецепты

### `ingredients` — справочник ингредиентов

Общий справочник (335 позиций в `db/seeds/ingredients.json`).

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `ingredient_id` | integer | PK | |
| `code` | text | да, уникален | стабильный код: `onion`, `milk`. По нему работают сиды, импорт и подбор товаров |
| `name` | text | да | «лук репчатый» |
| `synonyms` | text[] | да, `{}` | «лук», «репчатый лук» |
| `ingredient_group` | text | нет | овощи, молочные, мясо, крупы, специи… (25 групп) |
| `density_g_per_ml` | numeric | нет | плотность для перевода мл ↔ г |
| `piece_weight_g` | numeric | нет | вес штуки: луковица ≈ 100 г |

Группа нужна подбору цен: категория магазина «Молоко, масло, яйца» ищет только ингредиенты групп «молочные» и «яйца».

### `recipes` — рецепты

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `recipe_id` | integer | PK | |
| `couple_id` | integer | FK → couples, нет | `NULL` — общее блюдо (42 стартовых) |
| `title` | text | да | название |
| `default_servings` | integer | да, `2` | на сколько порций рецепт |
| `source_url` | text | нет | откуда импортирован |
| `tags` | text[] | да, `{}` | метки: суп, завтрак; фильтр списка блюд |
| `status` | text | да, `draft` | `draft` или `active` |

- `draft` — создан импортом, пара ещё не проверила. Не участвует в голосовании и плане: ошибка парсера не доходит до списка покупок.
- `active` — пара проверила. Стартовые блюда сразу `active`.

### `recipe_ingredients` — состав рецепта

Количество хранится на одну порцию, чтобы масштабировать на любое число порций.

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `id` | integer | PK | |
| `recipe_id` | integer | FK → recipes | |
| `ingredient_id` | integer | FK → ingredients, нет | `NULL`, если строку не разобрали |
| `per_serving` | numeric | нет | количество на порцию; `NULL`, если не разобрали |
| `unit` | text | да, `g` | `g`, `ml`, `pcs` |
| `optional` | boolean | да | «по вкусу», «для подачи» |
| `raw_text` | text | нет | исходная строка «2 ст. л. сахара» |
| `needs_review` | boolean | да | нужна проверка парой |

Строка без ингредиента или количества сохраняется только с `needs_review = true`: она не теряется и ждёт правки.

### `votes` — голоса за блюда

Голоса не скрываются: оба видят оба голоса.

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `recipe_id` | integer | FK → recipes | |
| `couple_id` | integer | да | пара голосующего |
| `user_id` | uuid | да | кто голосует |
| `value` | text | да | `want`, `neutral`, `dont_want` |

Ключ (`recipe_id`, `user_id`) — один голос на человека и блюдо. (`couple_id`, `user_id`) ссылается на `couple_members`: голосовать может только участник пары. Значения по умолчанию нет: голос появляется только когда человек проголосовал.

---

## 3. План, запасы, корзина

### `plan` — план недели

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `plan_id` | integer | PK | |
| `couple_id` | integer | FK → couples | |
| `week_start` | date | да | понедельник недели (проверяется) |
| `status` | text | да, `draft` | `draft` или `confirmed` |

Одна неделя на пару: уникально (`couple_id`, `week_start`).

### `plan_items` — блюда в плане

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `id` | integer | PK | |
| `plan_id` | integer | FK → plan | |
| `recipe_id` | integer | FK → recipes | |
| `servings` | integer | да, > 0 | сколько порций |
| `date` | date | нет | день; `NULL` — «на неделю, день не выбран» |
| `meal` | text | нет | `breakfast`, `lunch`, `dinner`, `snack`; только вместе с `date` |

В один день и приём пищи можно поставить несколько блюд. То, что `date` внутри недели плана, проверяет бэкенд.

### `pantry` — запасы

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `couple_id` | integer | FK → couples | |
| `ingredient_id` | integer | FK → ingredients | |
| `qty` | numeric | да, ≥ 0 | сколько есть |
| `unit` | text | да | `g`, `ml`, `pcs` |
| `source` | text | да, `manual` | `manual` — внесено руками, `leftover` — остаток от упаковки |

Ключ (`couple_id`, `ingredient_id`, `unit`, `source`). Корзина вычитает запасы из нужного количества.

### `cart_lines` — корзина

Список продуктов и есть корзина: строки считаются из плана и запасов, пара добавляет и убирает позиции.

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `id` | integer | PK | |
| `plan_id` | integer | FK → plan | |
| `ingredient_id` | integer | FK → ingredients, нет | `NULL` только у ручной позиции («салфетки») |
| `title` | text | да | как показывать |
| `qty` | numeric | да, > 0 | нужное количество |
| `unit` | text | да | `g`, `ml`, `pcs` |
| `excluded` | boolean | да | пара убрала строку |
| `added_manually` | boolean | да | добавлена руками |
| `qty_overridden` | boolean | да | пара сама задала количество вместо расчётного |
| `chosen_product_id` | integer | FK → products, нет | закреплённый товар (марка, вариант) |

Ручная позиция с ингредиентом склеивается с ним: «молоко» руками + молоко из рецептов = одна строка.

---

## 4. Магазины и цены

### `stores` — магазины

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `store_id` | integer | PK | |
| `code` | text | да, уникален | `dixy`, `magnit`, `manual` |
| `name` | text | да | «Магнит» |
| `collection_price` | boolean | да, `false` | сбор цен включён |

Сбор включается только после чтения условий магазина и записи одобрения ([stores.md](stores.md)).

### `store_location` — адрес пары в магазине

Цена зависит от адреса, поэтому он входит в ключ цены.

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `id` | integer | PK | |
| `store_id` | integer | FK → stores | |
| `couple_id` | integer | FK → couples | |
| `address` | text | нет | адрес |
| `region_key` | text | да | ключ магазина для цен (у Магнита `shopCode`, например `992301`) |
| `delivery_fee` | numeric(10,2) | нет | стоимость доставки |
| `free_delivery_from` | numeric(10,2) | нет | с какой суммы доставка бесплатна |

Один адрес пары на старте. Доставка пока не входит в итог.

### `products` — товары магазинов

Заполняет парсер цен.

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `id` | integer | PK | |
| `store_id` | integer | FK → stores | |
| `external_id` | text | да | номер товара у магазина |
| `title` | text | да | название на полке |
| `brand` | text | нет | марка |
| `sale_mode` | text | нет | `pack_mass` (упаковка по массе), `pack_count` (N штук), `per_piece` (поштучно), `by_weight` (на вес) |
| `pack_qty` | numeric | нет | размер упаковки |
| `pack_unit` | text | нет | `g`, `ml`, `pcs` |
| `category` | text | нет | категория магазина |

Уникально (`store_id`, `external_id`): повторный сбор обновляет товар, а не плодит копии.

### `ingredient_product_map` — какие товары подходят ингредиенту

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `ingredient_id` | integer | FK → ingredients | |
| `product_id` | integer | FK → products | |
| `preferred` | boolean | да | предпочтительный товар |
| `confidence` | numeric(3,2) | да, 0..1 | уверенность подбора |
| `confirmed_by_couple` | boolean | да | пара подтвердила |
| `matcher_version` | text | нет | версия правил подбора |

Ключ (`ingredient_id`, `product_id`). Вердикты: от 0.85 — `auto`, от 0.60 — нужно подтверждение, ниже — отказ.

### `prices` — цены

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `id` | bigint | PK | |
| `product_id` | integer | FK → products | |
| `location_id` | integer | FK → store_location | для какого адреса |
| `price` | numeric(10,2) | да, > 0 | цена упаковки |
| `card_price` | numeric(10,2) | нет | цена по карте |
| `price_per_kg` | numeric(10,2) | нет | цена за кг или л |
| `in_stock` | boolean | да, `true` | в наличии |
| `store_only` | boolean | да, `false` | только в магазине |
| `fetched_at` | timestamptz | да, `now()` | когда получена |
| `source` | text | да, `site` | `site`, `manual`, `receipt` |

Только INSERT. Индекс (`product_id`, `location_id`, `fetched_at desc`) — быстрая «последняя цена». Цена старше 3 дней помечается как устаревшая.

### `jobs` — очередь заданий

Мост между Go-бэкендом и Python-воркерами: Go кладёт строку, воркер берёт, выполняет и пишет результат.

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `id` | integer | PK | |
| `couple_id` | integer | FK → couples | чьё задание |
| `kind` | text | да | `import` (импорт рецепта) или `quote` (цены корзины) |
| `status` | text | да, `ждёт` | `ждёт` → `выполняется` → `готово` или `ошибка` |
| `params` | jsonb | да, `{}` | входные данные: `{"url": "…"}` |
| `result` | jsonb | нет | результат: черновик рецепта |
| `error` | text | нет | причина ошибки |
| `created_at` | timestamptz | да, `now()` | |
| `started_at` | timestamptz | нет | когда воркер взял задание; обязателен при `выполняется` |
| `attempts` | integer | да, `0` | сколько раз брали задание |
| `finished_at` | timestamptz | нет | |

При ошибке `result` = `{"error": {"code", "message"}}` (формат `Error` из OpenAPI), `error` — текст.
Задание, которое воркер взял и не завершил за 10 минут, возвращается в `ждёт`; после 3 попыток — `ошибка`
с кодом `job_failed`. Частичные индексы по ждущим и выполняющимся ускоряют выборку.
Воркер: [jobs/](../jobs/README.md). `started_at` и `attempts` добавляет миграция `0002_jobs_attempts.sql`.

---

## Доступ (RLS, набросок)

- **Таблицы пары** (`recipes` с `couple_id`, `plan`, `plan_items`, `pantry`, `cart_lines`, `store_location`, `jobs`, `votes`): доступ, если пользователь есть в `couple_members` этой пары. Таблицы без своего `couple_id` проверяются через `plan_id` или `recipe_id`.
- **Общие данные** (общие `recipes`, `ingredients`, `stores`, `products`, `prices`, `ingredient_product_map`): читать могут все вошедшие, писать — только сервисная роль.
- **`votes`**: читают оба в паре, пишет только владелец голоса.

Пример: Алиса из пары 1 просит план пары 1 — показан. Пётр из пары 2 просит план пары 1 — `ErrNotFound`.

## Как проверить схему

```bash
psql -v ON_ERROR_STOP=1 -f db/migrations/0001_init.sql -f db/migrations/checks/0001_init_checks.sql
```

Скрипт проверок вставляет пару Иван и Алиса, рецепты, голоса, план, корзину, цены и задание, проверяет, что
запрещённое (третий участник, второй голос, неделя не с понедельника, нулевая цена…) отклоняется, и откатывает всё.
