-- 0001_init: начальная схема.
-- Основа: дамп разработчика БД (cooking.sql, 16.10.2026). Структура и имена сохранены,
-- исправлены логические ошибки и добавлено то, без чего не работает код.
-- Каждое отличие от дампа перечислено в docs/schema.md, раздел «Отличия от cooking.sql».

BEGIN;

-- Пара и доступ ------------------------------------------------------------

CREATE TABLE couples (
    couple_id  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE couple_members (
    couple_id integer NOT NULL REFERENCES couples (couple_id) ON DELETE CASCADE,
    user_id   uuid NOT NULL,  -- auth.users(id) в Supabase
    role      text NOT NULL CHECK (role IN ('owner', 'partner')),
    PRIMARY KEY (couple_id, user_id)
);

-- В паре не больше двух человек. CHECK так не умеет, нужен триггер.
CREATE FUNCTION couple_members_max_two() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM couples WHERE couple_id = NEW.couple_id FOR UPDATE;  -- против гонки двух вставок
    IF (SELECT count(*) FROM couple_members WHERE couple_id = NEW.couple_id) >= 2 THEN
        RAISE EXCEPTION 'в паре % уже два участника', NEW.couple_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER couple_members_max_two
    BEFORE INSERT ON couple_members
    FOR EACH ROW EXECUTE FUNCTION couple_members_max_two();

-- Справочник и рецепты -----------------------------------------------------

CREATE TABLE ingredients (
    ingredient_id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code             text NOT NULL UNIQUE,  -- стабильный код из сидов: onion, milk
    name             text NOT NULL,
    synonyms         text[] NOT NULL DEFAULT '{}',
    ingredient_group text,
    density_g_per_ml numeric CHECK (density_g_per_ml > 0),
    piece_weight_g   numeric CHECK (piece_weight_g > 0)
);

CREATE TABLE recipes (
    recipe_id        integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    couple_id        integer REFERENCES couples (couple_id) ON DELETE CASCADE,  -- NULL: общее блюдо
    title            text NOT NULL,
    default_servings integer NOT NULL DEFAULT 2 CHECK (default_servings > 0),
    source_url       text,
    tags             text[] NOT NULL DEFAULT '{}',  -- метки: суп, завтрак; фильтр списка блюд
    status           text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active'))
);

CREATE TABLE recipe_ingredients (
    id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipe_id     integer NOT NULL REFERENCES recipes (recipe_id) ON DELETE CASCADE,
    ingredient_id integer REFERENCES ingredients (ingredient_id),  -- NULL: строка не разобрана
    per_serving   numeric CHECK (per_serving > 0),                 -- NULL: количество не разобрано
    unit          text NOT NULL DEFAULT 'g' CHECK (unit IN ('g', 'ml', 'pcs')),
    optional      boolean NOT NULL DEFAULT false,
    raw_text      text,
    needs_review  boolean NOT NULL DEFAULT false,
    CHECK (needs_review OR (ingredient_id IS NOT NULL AND per_serving IS NOT NULL))
);

CREATE TABLE votes (
    recipe_id integer NOT NULL REFERENCES recipes (recipe_id) ON DELETE CASCADE,
    couple_id integer NOT NULL,
    user_id   uuid NOT NULL,
    value     text NOT NULL CHECK (value IN ('want', 'neutral', 'dont_want')),
    PRIMARY KEY (recipe_id, user_id),
    FOREIGN KEY (couple_id, user_id) REFERENCES couple_members (couple_id, user_id) ON DELETE CASCADE
);

-- План, запасы, корзина ----------------------------------------------------

CREATE TABLE plan (
    plan_id    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    couple_id  integer NOT NULL REFERENCES couples (couple_id) ON DELETE CASCADE,
    week_start date NOT NULL CHECK (extract(isodow FROM week_start) = 1),  -- понедельник
    status     text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed')),
    UNIQUE (couple_id, week_start)
);

CREATE TABLE plan_items (
    id        integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plan_id   integer NOT NULL REFERENCES plan (plan_id) ON DELETE CASCADE,
    recipe_id integer NOT NULL REFERENCES recipes (recipe_id),
    servings  integer NOT NULL CHECK (servings > 0),
    date      date,
    meal      text CHECK (meal IN ('breakfast', 'lunch', 'dinner', 'snack')),
    CHECK (meal IS NULL OR date IS NOT NULL)
);

CREATE TABLE pantry (
    couple_id     integer NOT NULL REFERENCES couples (couple_id) ON DELETE CASCADE,
    ingredient_id integer NOT NULL REFERENCES ingredients (ingredient_id),
    qty           numeric NOT NULL CHECK (qty >= 0),
    unit          text NOT NULL DEFAULT 'g' CHECK (unit IN ('g', 'ml', 'pcs')),
    source        text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'leftover')),
    PRIMARY KEY (couple_id, ingredient_id, unit, source)
);

-- Магазины и цены ----------------------------------------------------------
-- (cart_lines ссылается на products, поэтому создаётся после них, см. ниже)

CREATE TABLE stores (
    store_id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code             text NOT NULL UNIQUE,  -- dixy, magnit, manual
    name             text NOT NULL,
    collection_price boolean NOT NULL DEFAULT false
);

CREATE TABLE store_location (
    id                 integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_id           integer NOT NULL REFERENCES stores (store_id),
    couple_id          integer NOT NULL REFERENCES couples (couple_id) ON DELETE CASCADE,
    address            text,
    region_key         text NOT NULL,  -- для Магнита shopCode
    delivery_fee       numeric(10, 2),
    free_delivery_from numeric(10, 2)
);

CREATE TABLE products (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_id    integer NOT NULL REFERENCES stores (store_id),
    external_id text NOT NULL,
    title       text NOT NULL,
    brand       text,
    sale_mode   text CHECK (sale_mode IN ('pack_mass', 'pack_count', 'per_piece', 'by_weight')),
    pack_qty    numeric CHECK (pack_qty > 0),
    pack_unit   text CHECK (pack_unit IN ('g', 'ml', 'pcs')),
    category    text,
    UNIQUE (store_id, external_id)
);

CREATE TABLE ingredient_product_map (
    ingredient_id       integer NOT NULL REFERENCES ingredients (ingredient_id),
    product_id          integer NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    preferred           boolean NOT NULL DEFAULT false,
    confidence          numeric(3, 2) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    confirmed_by_couple boolean NOT NULL DEFAULT false,
    matcher_version     text,
    PRIMARY KEY (ingredient_id, product_id)
);

-- Корзина: список продуктов плана. Ручная позиция может быть без ингредиента.
CREATE TABLE cart_lines (
    id                integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plan_id           integer NOT NULL REFERENCES plan (plan_id) ON DELETE CASCADE,
    ingredient_id     integer REFERENCES ingredients (ingredient_id),
    title             text NOT NULL,
    qty               numeric NOT NULL CHECK (qty > 0),
    unit              text NOT NULL DEFAULT 'g' CHECK (unit IN ('g', 'ml', 'pcs')),
    excluded          boolean NOT NULL DEFAULT false,
    added_manually    boolean NOT NULL DEFAULT false,
    qty_overridden    boolean NOT NULL DEFAULT false,  -- пара сама задала количество
    chosen_product_id integer REFERENCES products (id) ON DELETE SET NULL,
    CHECK (added_manually OR ingredient_id IS NOT NULL)
);

CREATE INDEX cart_lines_plan_idx ON cart_lines (plan_id);

-- Только INSERT: история цен не перезаписывается.
CREATE TABLE prices (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id   integer NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    location_id  integer NOT NULL REFERENCES store_location (id) ON DELETE CASCADE,
    price        numeric(10, 2) NOT NULL CHECK (price > 0),
    card_price   numeric(10, 2) CHECK (card_price > 0),
    price_per_kg numeric(10, 2) CHECK (price_per_kg > 0),
    in_stock     boolean NOT NULL DEFAULT true,
    store_only   boolean NOT NULL DEFAULT false,
    fetched_at   timestamptz NOT NULL DEFAULT now(),
    source       text NOT NULL DEFAULT 'site' CHECK (source IN ('site', 'manual', 'receipt'))
);

CREATE INDEX prices_latest_idx ON prices (product_id, location_id, fetched_at DESC);

-- Задания для Python-воркеров ----------------------------------------------

CREATE TABLE jobs (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    couple_id   integer NOT NULL REFERENCES couples (couple_id) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('import', 'quote')),
    status      text NOT NULL DEFAULT 'ждёт'
                CHECK (status IN ('ждёт', 'выполняется', 'готово', 'ошибка')),
    params      jsonb NOT NULL DEFAULT '{}',
    result      jsonb,
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

CREATE INDEX jobs_waiting_idx ON jobs (created_at) WHERE status = 'ждёт';

-- Индексы по внешним ключам, по которым идут выборки пары.
CREATE INDEX recipes_couple_idx ON recipes (couple_id);
CREATE INDEX recipe_ingredients_recipe_idx ON recipe_ingredients (recipe_id);
CREATE INDEX plan_items_plan_idx ON plan_items (plan_id);
CREATE INDEX store_location_couple_idx ON store_location (couple_id);

COMMIT;
