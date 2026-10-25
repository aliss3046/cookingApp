-- Проверки миграции 0001_init на примерах. Запуск на пустой базе после миграции:
--   psql -v ON_ERROR_STOP=1 -f db/migrations/0001_init.sql -f db/migrations/checks/0001_init_checks.sql
-- Всё выполняется в транзакции и откатывается. Ошибка = проверка не прошла.

BEGIN;

CREATE FUNCTION pg_temp.must_fail(sql text, what text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE sql;
    EXCEPTION WHEN integrity_constraint_violation OR check_violation OR not_null_violation
                   OR unique_violation OR foreign_key_violation THEN
        RETURN;
    END;
    RAISE EXCEPTION 'ожидался отказ: %', what;
END $$;

-- Пара Иван и Алиса.
INSERT INTO couples (name) VALUES ('Иван и Алиса');
INSERT INTO couple_members VALUES (1, '00000000-0000-0000-0000-000000000001', 'owner');
INSERT INTO couple_members VALUES (1, '00000000-0000-0000-0000-000000000002', 'partner');
SELECT pg_temp.must_fail($$INSERT INTO couple_members VALUES (1, '00000000-0000-0000-0000-000000000003', 'partner')$$,
                         'третий участник пары');
SELECT pg_temp.must_fail($$INSERT INTO couple_members VALUES (1, '00000000-0000-0000-0000-000000000004', 'boss')$$,
                         'неизвестная роль');

-- Справочник: стабильный код обязателен и уникален.
INSERT INTO ingredients (code, name, synonyms, ingredient_group, piece_weight_g)
VALUES ('onion', 'лук репчатый', '{лук}', 'овощи', 100), ('milk', 'молоко', '{}', 'молочные', NULL);
SELECT pg_temp.must_fail($$INSERT INTO ingredients (code, name) VALUES ('onion', 'дубль')$$, 'повтор кода');

-- Общее блюдо без пары и строка, которую не удалось разобрать.
INSERT INTO recipes (couple_id, title, status) VALUES (NULL, 'Омлет', 'active');
INSERT INTO recipe_ingredients (recipe_id, ingredient_id, per_serving, unit) VALUES (1, 2, 100, 'ml');
INSERT INTO recipe_ingredients (recipe_id, raw_text, needs_review) VALUES (1, 'соль по вкусу', true);
SELECT pg_temp.must_fail($$INSERT INTO recipe_ingredients (recipe_id, raw_text) VALUES (1, 'без разбора и без пометки')$$,
                         'неразобранная строка без needs_review');
SELECT pg_temp.must_fail($$INSERT INTO recipes (title, status) VALUES ('X', 'confirmed')$$, 'старый статус confirmed');

-- Голос: один на человека и блюдо, только от участника пары.
INSERT INTO votes VALUES (1, 1, '00000000-0000-0000-0000-000000000001', 'want');
INSERT INTO votes VALUES (1, 1, '00000000-0000-0000-0000-000000000002', 'dont_want');
SELECT pg_temp.must_fail($$INSERT INTO votes VALUES (1, 1, '00000000-0000-0000-0000-000000000001', 'neutral')$$,
                         'второй голос того же человека');
SELECT pg_temp.must_fail($$INSERT INTO votes VALUES (1, 1, '00000000-0000-0000-0000-000000000009', 'want')$$,
                         'голос не участника пары');
SELECT pg_temp.must_fail($$INSERT INTO votes (recipe_id, couple_id, user_id) VALUES (1, 1, '00000000-0000-0000-0000-000000000002')$$,
                         'голос без значения');

-- План: неделя с понедельника, одна на пару; приём пищи только с датой.
INSERT INTO plan (couple_id, week_start) VALUES (1, '2026-10-26');
SELECT pg_temp.must_fail($$INSERT INTO plan (couple_id, week_start) VALUES (1, '2026-10-28')$$, 'неделя не с понедельника');
SELECT pg_temp.must_fail($$INSERT INTO plan (couple_id, week_start) VALUES (1, '2026-10-26')$$, 'вторая такая же неделя');
INSERT INTO plan_items (plan_id, recipe_id, servings, date, meal) VALUES (1, 1, 2, '2026-10-27', 'breakfast');
INSERT INTO plan_items (plan_id, recipe_id, servings) VALUES (1, 1, 2);
SELECT pg_temp.must_fail($$INSERT INTO plan_items (plan_id, recipe_id, servings, meal) VALUES (1, 1, 2, 'dinner')$$,
                         'приём пищи без даты');

-- Корзина: ручная позиция без ингредиента разрешена, обычная без ингредиента нет.
INSERT INTO cart_lines (plan_id, title, qty, unit, added_manually) VALUES (1, 'салфетки', 1, 'pcs', true);
SELECT pg_temp.must_fail($$INSERT INTO cart_lines (plan_id, title, qty) VALUES (1, 'нечто', 1)$$,
                         'строка из рецепта без ингредиента');

-- Магазин, адрес, товар, подбор, цены.
INSERT INTO stores (code, name, collection_price) VALUES ('magnit', 'Магнит', true);
INSERT INTO store_location (store_id, couple_id, address, region_key) VALUES (1, 1, 'Москва', '992301');
INSERT INTO products (store_id, external_id, title, pack_qty, pack_unit, sale_mode)
VALUES (1, '1000246228', 'Молоко 2.5% 1.4л', 1400, 'ml', 'pack_mass');
SELECT pg_temp.must_fail($$INSERT INTO products (store_id, external_id, title) VALUES (1, '1000246228', 'дубль')$$,
                         'повтор товара магазина');
INSERT INTO ingredient_product_map (ingredient_id, product_id, confidence) VALUES (2, 1, 0.92);
SELECT pg_temp.must_fail($$INSERT INTO ingredient_product_map (ingredient_id, product_id, confidence) VALUES (1, 1, 1.5)$$,
                         'уверенность больше 1');
INSERT INTO prices (product_id, location_id, price, price_per_kg) VALUES (1, 1, 157.99, 112.85);
INSERT INTO prices (product_id, location_id, price) VALUES (1, 1, 149.99);  -- история: вторая строка
SELECT pg_temp.must_fail($$INSERT INTO prices (product_id, location_id, price) VALUES (1, 1, 0)$$, 'нулевая цена');

-- Задание: новое по умолчанию ждёт, а не «выполняется».
INSERT INTO jobs (couple_id, kind, params) VALUES (1, 'import', '{"url": "https://example.test/r"}');
DO $$ BEGIN
    IF (SELECT status FROM jobs) <> 'ждёт' THEN RAISE EXCEPTION 'новое задание должно ждать'; END IF;
    IF (SELECT count(*) FROM prices) <> 2 THEN RAISE EXCEPTION 'цены должны копиться'; END IF;
END $$;

-- Удаление пары убирает её данные, общий рецепт остаётся.
DELETE FROM couples WHERE couple_id = 1;
DO $$ BEGIN
    IF (SELECT count(*) FROM recipes) <> 1 THEN RAISE EXCEPTION 'общий рецепт пропал'; END IF;
    IF (SELECT count(*) FROM plan) + (SELECT count(*) FROM votes) + (SELECT count(*) FROM jobs) <> 0 THEN
        RAISE EXCEPTION 'данные пары остались после удаления';
    END IF;
END $$;

SELECT 'все проверки прошли' AS result;
ROLLBACK;
