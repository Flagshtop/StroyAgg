"""Работа с PostgreSQL (psycopg 3)."""
from __future__ import annotations

from .config import DbConfig
from .models import Offer

SCHEMA_SQL = """
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
"""

INSERT_SQL = """
INSERT INTO offers (run_id, query, marketplace, title, price, delivery_text, delivery_days,
                    delivery_date, order_url, is_best_price, is_fastest, found_at)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
"""


class Database:
    def __init__(self, cfg: DbConfig):
        self.cfg = cfg

    def connect(self):
        import psycopg

        return psycopg.connect(
            host=self.cfg.host, port=self.cfg.port, dbname=self.cfg.dbname,
            user=self.cfg.user, password=self.cfg.password, sslmode=self.cfg.sslmode,
            connect_timeout=8, application_name="StroyAgg",
        )

    def test(self) -> str:
        with self.connect() as conn:
            return conn.execute("select version()").fetchone()[0]

    def init_schema(self):
        with self.connect() as conn:
            conn.execute(SCHEMA_SQL)

    def save(self, offers: list[Offer]) -> int:
        """Сохраняет предложения одним поиском (run). Возвращает id поиска."""
        if not offers:
            raise ValueError("Нет данных для сохранения")
        queries = list(dict.fromkeys(o.query for o in offers))
        markets = list(dict.fromkeys(o.marketplace for o in offers))
        with self.connect() as conn:
            conn.execute(SCHEMA_SQL)
            with conn.transaction():
                run_id = conn.execute(
                    "INSERT INTO search_runs (queries, marketplaces, offers_count) VALUES (%s,%s,%s) RETURNING id",
                    (queries, markets, len(offers)),
                ).fetchone()[0]
                with conn.cursor() as cur:
                    cur.executemany(INSERT_SQL, [
                        (run_id, o.query, o.marketplace, o.title or "(без названия)", o.price, o.delivery_text,
                         o.delivery_days, o.delivery_date, o.url, o.is_best_price, o.is_fastest, o.found_at)
                        for o in offers
                    ])
        return run_id
