# ADR-0001: Стек бэкенда

Статус: предложено

**Выбрано:** Supabase (PostgreSQL, Auth, Realtime, RLS; Frankfurt), Python + FastAPI + Pydantic для API и расчёта, Python + httpx + BeautifulSoup (+ Playwright при необходимости) для воркера цен, pytest.

**Почему:** реляционные данные; общая корзина обновляется у двоих через Realtime без своего сервера; OpenAPI из коробки в FastAPI; помещается в бюджет до 5 €/мес; фронтенд не привязан к фреймворку.

**Альтернативы:** свой Postgres + собственные WebSocket (дороже в поддержке); Firebase (нереляционная модель, сложнее цепочка блюдо→товар→цена); Node/NestJS (нет преимущества, а парсеры удобнее на Python).
