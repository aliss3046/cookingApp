--
-- PostgreSQL database dump
--

-- Dumped from database version 17.4
-- Dumped by pg_dump version 17.4

-- Started on 2026-10-16 22:53:51

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- TOC entry 241 (class 1259 OID 33185)
-- Name: cart_lines; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.cart_lines (
    id integer NOT NULL,
    plan_id integer NOT NULL,
    ingredient_id integer NOT NULL,
    title text,
    qty numeric,
    unit text DEFAULT 'g'::text,
    excluded boolean,
    added_manually boolean,
    CONSTRAINT cart_lines_unit_check CHECK ((unit = ANY (ARRAY['g'::text, 'ml'::text, 'pcs'::text])))
);


ALTER TABLE public.cart_lines OWNER TO postgres;

--
-- TOC entry 240 (class 1259 OID 33184)
-- Name: cart_lines_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.cart_lines ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.cart_lines_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- TOC entry 219 (class 1259 OID 32892)
-- Name: couple_members; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.couple_members (
    couple_id integer NOT NULL,
    user_id uuid NOT NULL,
    role text
);


ALTER TABLE public.couple_members OWNER TO postgres;

--
-- TOC entry 218 (class 1259 OID 32884)
-- Name: couples; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.couples (
    couples_id integer NOT NULL,
    name text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.couples OWNER TO postgres;

--
-- TOC entry 217 (class 1259 OID 32883)
-- Name: couples_couples_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.couples ALTER COLUMN couples_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.couples_couples_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- TOC entry 235 (class 1259 OID 33103)
-- Name: ingredient_product_map; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ingredient_product_map (
    ingredient_id integer NOT NULL,
    product_id integer NOT NULL,
    preferred boolean,
    confidence numeric,
    confirmed_by_couple boolean
);


ALTER TABLE public.ingredient_product_map OWNER TO postgres;

--
-- TOC entry 225 (class 1259 OID 32940)
-- Name: ingredients; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ingredients (
    ingredint_id integer NOT NULL,
    name text NOT NULL,
    ingredient_group text,
    piece_weight_g numeric,
    CONSTRAINT ingredients_piece_weight_g_check CHECK ((piece_weight_g > (0)::numeric))
);


ALTER TABLE public.ingredients OWNER TO postgres;

--
-- TOC entry 224 (class 1259 OID 32939)
-- Name: ingredients_ingredint_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.ingredients ALTER COLUMN ingredint_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.ingredients_ingredint_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- TOC entry 234 (class 1259 OID 33083)
-- Name: jobs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.jobs (
    id integer NOT NULL,
    couple_id integer NOT NULL,
    kind text NOT NULL,
    status text DEFAULT 'выполняется'::text NOT NULL,
    error text,
    created_at timestamp with time zone,
    finished_at timestamp with time zone,
    CONSTRAINT jobs_status_check CHECK ((status = ANY (ARRAY['ждёт'::text, 'выполняется'::text, 'готово'::text, 'ошибка'::text])))
);


ALTER TABLE public.jobs OWNER TO postgres;

--
-- TOC entry 233 (class 1259 OID 33082)
-- Name: jobs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.jobs ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.jobs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- TOC entry 242 (class 1259 OID 33225)
-- Name: pantry; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.pantry (
    couple_id integer NOT NULL,
    ingredient_id integer NOT NULL,
    qty numeric,
    unit text DEFAULT 'g'::text,
    source text,
    CONSTRAINT pantry_source_check CHECK ((source = ANY (ARRAY['manual'::text, 'leftover'::text]))),
    CONSTRAINT pantry_unit_check CHECK ((unit = ANY (ARRAY['g'::text, 'ml'::text, 'pcs'::text])))
);


ALTER TABLE public.pantry OWNER TO postgres;

--
-- TOC entry 223 (class 1259 OID 32928)
-- Name: plan; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.plan (
    plan_id integer NOT NULL,
    couples_id integer NOT NULL,
    week_start timestamp without time zone DEFAULT now() NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    CONSTRAINT plan_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'confirmed'::text])))
);


ALTER TABLE public.plan OWNER TO postgres;

--
-- TOC entry 239 (class 1259 OID 33169)
-- Name: plan_items; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.plan_items (
    id integer NOT NULL,
    plan_id integer NOT NULL,
    recipe_id integer NOT NULL,
    servings integer NOT NULL,
    date date
);


ALTER TABLE public.plan_items OWNER TO postgres;

--
-- TOC entry 238 (class 1259 OID 33168)
-- Name: plan_items_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.plan_items ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.plan_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- TOC entry 222 (class 1259 OID 32927)
-- Name: plan_plan_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.plan ALTER COLUMN plan_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.plan_plan_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- TOC entry 232 (class 1259 OID 33057)
-- Name: prices; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.prices (
    product_id integer NOT NULL,
    location_id integer NOT NULL,
    price numeric NOT NULL,
    in_stock boolean,
    store_only boolean,
    fetched_at timestamp with time zone,
    source text
);


ALTER TABLE public.prices OWNER TO postgres;

--
-- TOC entry 229 (class 1259 OID 33002)
-- Name: products; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.products (
    id integer NOT NULL,
    store_id integer NOT NULL,
    external_id text NOT NULL,
    title text NOT NULL,
    category text
);


ALTER TABLE public.products OWNER TO postgres;

--
-- TOC entry 228 (class 1259 OID 33001)
-- Name: products_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.products ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.products_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- TOC entry 236 (class 1259 OID 33122)
-- Name: recipe_ingredients; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.recipe_ingredients (
    recipes_id integer NOT NULL,
    ingredient_id integer NOT NULL,
    per_serving numeric NOT NULL,
    unit text DEFAULT 'g'::text NOT NULL,
    optional boolean,
    raw_text text,
    needs_review boolean,
    CONSTRAINT recipe_ingredients_unit_check CHECK ((unit = ANY (ARRAY['g'::text, 'ml'::text, 'pcs'::text])))
);


ALTER TABLE public.recipe_ingredients OWNER TO postgres;

--
-- TOC entry 221 (class 1259 OID 32910)
-- Name: recipes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.recipes (
    recipes_id integer NOT NULL,
    couples_id integer NOT NULL,
    title text,
    default_servings integer DEFAULT 2 NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    CONSTRAINT recipes_default_servings_check CHECK ((default_servings > 0)),
    CONSTRAINT recipes_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'active'::text])))
);


ALTER TABLE public.recipes OWNER TO postgres;

--
-- TOC entry 220 (class 1259 OID 32909)
-- Name: recipes_recipes_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.recipes ALTER COLUMN recipes_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.recipes_recipes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- TOC entry 231 (class 1259 OID 33040)
-- Name: store_location; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.store_location (
    id integer NOT NULL,
    store_id integer NOT NULL,
    couple_id integer NOT NULL,
    adress text,
    region_key text NOT NULL,
    delivery_fee numeric,
    free_delivery_from numeric
);


ALTER TABLE public.store_location OWNER TO postgres;

--
-- TOC entry 230 (class 1259 OID 33039)
-- Name: store_location_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.store_location ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.store_location_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- TOC entry 227 (class 1259 OID 32953)
-- Name: stores; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.stores (
    store_id integer NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    collection_price boolean DEFAULT false NOT NULL
);


ALTER TABLE public.stores OWNER TO postgres;

--
-- TOC entry 226 (class 1259 OID 32952)
-- Name: stores_store_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.stores ALTER COLUMN store_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.stores_store_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- TOC entry 237 (class 1259 OID 33151)
-- Name: votes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.votes (
    recipes_id integer NOT NULL,
    couple_id integer NOT NULL,
    user_id uuid NOT NULL,
    value text DEFAULT 'dont want'::text NOT NULL,
    CONSTRAINT votes_value_check CHECK ((value = ANY (ARRAY['want'::text, 'dont want'::text, 'neutral'::text])))
);


ALTER TABLE public.votes OWNER TO postgres;

--
-- TOC entry 4752 (class 2606 OID 33193)
-- Name: cart_lines cart_lines_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cart_lines
    ADD CONSTRAINT cart_lines_pkey PRIMARY KEY (id);


--
-- TOC entry 4734 (class 2606 OID 32898)
-- Name: couple_members couple_members_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.couple_members
    ADD CONSTRAINT couple_members_pkey PRIMARY KEY (couple_id, user_id);


--
-- TOC entry 4732 (class 2606 OID 32891)
-- Name: couples couples_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.couples
    ADD CONSTRAINT couples_pkey PRIMARY KEY (couples_id);


--
-- TOC entry 4740 (class 2606 OID 32947)
-- Name: ingredients ingredients_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ingredients
    ADD CONSTRAINT ingredients_pkey PRIMARY KEY (ingredint_id);


--
-- TOC entry 4748 (class 2606 OID 33091)
-- Name: jobs jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (id);


--
-- TOC entry 4750 (class 2606 OID 33173)
-- Name: plan_items plan_items_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.plan_items
    ADD CONSTRAINT plan_items_pkey PRIMARY KEY (id);


--
-- TOC entry 4738 (class 2606 OID 32933)
-- Name: plan plan_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.plan
    ADD CONSTRAINT plan_pkey PRIMARY KEY (plan_id);


--
-- TOC entry 4744 (class 2606 OID 33008)
-- Name: products products_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (id);


--
-- TOC entry 4736 (class 2606 OID 32918)
-- Name: recipes recipes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.recipes
    ADD CONSTRAINT recipes_pkey PRIMARY KEY (recipes_id);


--
-- TOC entry 4746 (class 2606 OID 33046)
-- Name: store_location store_location_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.store_location
    ADD CONSTRAINT store_location_pkey PRIMARY KEY (id);


--
-- TOC entry 4742 (class 2606 OID 32960)
-- Name: stores stores_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stores
    ADD CONSTRAINT stores_pkey PRIMARY KEY (store_id);


--
-- TOC entry 4770 (class 2606 OID 33199)
-- Name: cart_lines cart_lines_ingredient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cart_lines
    ADD CONSTRAINT cart_lines_ingredient_id_fkey FOREIGN KEY (ingredient_id) REFERENCES public.ingredients(ingredint_id);


--
-- TOC entry 4771 (class 2606 OID 33194)
-- Name: cart_lines cart_lines_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cart_lines
    ADD CONSTRAINT cart_lines_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.plan(plan_id);


--
-- TOC entry 4753 (class 2606 OID 32899)
-- Name: couple_members couple_members_couple_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.couple_members
    ADD CONSTRAINT couple_members_couple_id_fkey FOREIGN KEY (couple_id) REFERENCES public.couples(couples_id);


--
-- TOC entry 4762 (class 2606 OID 33108)
-- Name: ingredient_product_map ingredient_product_map_ingredient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ingredient_product_map
    ADD CONSTRAINT ingredient_product_map_ingredient_id_fkey FOREIGN KEY (ingredient_id) REFERENCES public.ingredients(ingredint_id);


--
-- TOC entry 4763 (class 2606 OID 33113)
-- Name: ingredient_product_map ingredient_product_map_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ingredient_product_map
    ADD CONSTRAINT ingredient_product_map_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- TOC entry 4761 (class 2606 OID 33092)
-- Name: jobs jobs_couple_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_couple_id_fkey FOREIGN KEY (couple_id) REFERENCES public.couples(couples_id);


--
-- TOC entry 4772 (class 2606 OID 33233)
-- Name: pantry pantry_couple_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.pantry
    ADD CONSTRAINT pantry_couple_id_fkey FOREIGN KEY (couple_id) REFERENCES public.couples(couples_id);


--
-- TOC entry 4773 (class 2606 OID 33238)
-- Name: pantry pantry_ingredient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.pantry
    ADD CONSTRAINT pantry_ingredient_id_fkey FOREIGN KEY (ingredient_id) REFERENCES public.ingredients(ingredint_id);


--
-- TOC entry 4755 (class 2606 OID 32934)
-- Name: plan plan_couples_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.plan
    ADD CONSTRAINT plan_couples_id_fkey FOREIGN KEY (couples_id) REFERENCES public.couples(couples_id);


--
-- TOC entry 4768 (class 2606 OID 33174)
-- Name: plan_items plan_items_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.plan_items
    ADD CONSTRAINT plan_items_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.plan(plan_id);


--
-- TOC entry 4769 (class 2606 OID 33179)
-- Name: plan_items plan_items_recipe_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.plan_items
    ADD CONSTRAINT plan_items_recipe_id_fkey FOREIGN KEY (recipe_id) REFERENCES public.recipes(recipes_id);


--
-- TOC entry 4759 (class 2606 OID 33067)
-- Name: prices prices_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.prices
    ADD CONSTRAINT prices_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.store_location(id);


--
-- TOC entry 4760 (class 2606 OID 33062)
-- Name: prices prices_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.prices
    ADD CONSTRAINT prices_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);


--
-- TOC entry 4756 (class 2606 OID 33009)
-- Name: products products_store_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- TOC entry 4764 (class 2606 OID 33134)
-- Name: recipe_ingredients recipe_ingredients_ingredient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.recipe_ingredients
    ADD CONSTRAINT recipe_ingredients_ingredient_id_fkey FOREIGN KEY (ingredient_id) REFERENCES public.ingredients(ingredint_id);


--
-- TOC entry 4765 (class 2606 OID 33129)
-- Name: recipe_ingredients recipe_ingredients_recipes_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.recipe_ingredients
    ADD CONSTRAINT recipe_ingredients_recipes_id_fkey FOREIGN KEY (recipes_id) REFERENCES public.recipes(recipes_id);


--
-- TOC entry 4754 (class 2606 OID 32919)
-- Name: recipes recipes_couples_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.recipes
    ADD CONSTRAINT recipes_couples_id_fkey FOREIGN KEY (couples_id) REFERENCES public.couples(couples_id);


--
-- TOC entry 4757 (class 2606 OID 33052)
-- Name: store_location store_location_couple_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.store_location
    ADD CONSTRAINT store_location_couple_id_fkey FOREIGN KEY (couple_id) REFERENCES public.couples(couples_id);


--
-- TOC entry 4758 (class 2606 OID 33047)
-- Name: store_location store_location_store_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.store_location
    ADD CONSTRAINT store_location_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(store_id);


--
-- TOC entry 4766 (class 2606 OID 33163)
-- Name: votes votes_couple_id_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.votes
    ADD CONSTRAINT votes_couple_id_user_id_fkey FOREIGN KEY (couple_id, user_id) REFERENCES public.couple_members(couple_id, user_id);


--
-- TOC entry 4767 (class 2606 OID 33158)
-- Name: votes votes_recipes_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.votes
    ADD CONSTRAINT votes_recipes_id_fkey FOREIGN KEY (recipes_id) REFERENCES public.recipes(recipes_id);


-- Completed on 2026-10-16 22:53:52

--
-- PostgreSQL database dump complete
--

