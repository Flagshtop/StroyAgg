-- Схема БД StroyAgg (PostgreSQL). Программа создаёт её сама, файл — для справки/DBA.
CREATE TABLE IF NOT EXISTS search_runs (
    id          BIGSERIAL PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    queries     TEXT[]      NOT NULL,
    marketplaces TEXT[]     NOT NULL,
    offers_count INTEGER    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS offers (
    id             BIGSERIAL PRIMARY KEY,
    run_id         BIGINT REFERENCES search_runs(id) ON DELETE CASCADE,
    query          TEXT        NOT NULL,
    marketplace    TEXT        NOT NULL,
    title          TEXT        NOT NULL,
    price          NUMERIC(14,2),
    currency       CHAR(3)     NOT NULL DEFAULT 'RUB',
    delivery_text  TEXT,
    delivery_days  INTEGER,
    delivery_date  DATE,
    order_url      TEXT        NOT NULL,
    is_best_price  BOOLEAN     NOT NULL DEFAULT FALSE,
    is_fastest     BOOLEAN     NOT NULL DEFAULT FALSE,
    found_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS offers_query_idx       ON offers (lower(query));
CREATE INDEX IF NOT EXISTS offers_marketplace_idx ON offers (marketplace);
CREATE INDEX IF NOT EXISTS offers_found_at_idx    ON offers (found_at DESC);

-- Последний поиск по каждому запросу: все предложения, от дешёвого к дорогому
CREATE OR REPLACE VIEW v_latest_offers AS
SELECT o.*
FROM offers o
JOIN (SELECT lower(query) AS q, max(run_id) AS run_id FROM offers GROUP BY lower(query)) l
  ON lower(o.query) = l.q AND o.run_id = l.run_id;

-- Лучшая цена и самая быстрая доставка по каждому запросу (из последнего поиска)
CREATE OR REPLACE VIEW v_best_offers AS
SELECT DISTINCT ON (lower(query))
       query, marketplace, title, price, delivery_text, delivery_days, delivery_date, order_url, found_at,
       'лучшая цена'::text AS reason
FROM v_latest_offers WHERE price IS NOT NULL
ORDER BY lower(query), price, delivery_days NULLS LAST
;
CREATE OR REPLACE VIEW v_fastest_offers AS
SELECT DISTINCT ON (lower(query))
       query, marketplace, title, price, delivery_text, delivery_days, delivery_date, order_url, found_at,
       'быстрая доставка'::text AS reason
FROM v_latest_offers WHERE delivery_days IS NOT NULL
ORDER BY lower(query), delivery_days, price NULLS LAST
;
