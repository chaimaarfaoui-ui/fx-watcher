-- FX Watcher v2 schema (PostgreSQL 16)

-- WHAT we watch. Change rows here, not code.
CREATE TABLE watch_pairs (
    base          TEXT NOT NULL,                       -- e.g. EUR
    quote         TEXT NOT NULL,                       -- e.g. TND  (1 base = x quote)
    threshold_pct NUMERIC(6,3) NOT NULL DEFAULT 0.5,   -- alert if the rate moves this % between two updates
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (base, quote)
);

-- WHAT it costs the business: money paid in foreign currency every month.
CREATE TABLE import_exposure (
    id             SERIAL PRIMARY KEY,
    label          TEXT NOT NULL,
    currency       TEXT NOT NULL,
    monthly_amount NUMERIC(14,2) NOT NULL CHECK (monthly_amount >= 0)
);

-- The rate the company used in its budget. Finance teams think in "budget rate vs actual".
CREATE TABLE budget_rates (
    base          TEXT NOT NULL,
    quote         TEXT NOT NULL,
    budget_rate   NUMERIC(14,6) NOT NULL CHECK (budget_rate > 0),
    tolerance_pct NUMERIC(6,3) NOT NULL DEFAULT 2 CHECK (tolerance_pct >= 0),
    PRIMARY KEY (base, quote)
);

-- Collected data: one row per (pair, provider update).
-- The API refreshes once a day; the UNIQUE key makes re-collecting harmless (idempotent).
CREATE TABLE fx_rates (
    id                  SERIAL PRIMARY KEY,
    base                TEXT NOT NULL,
    quote               TEXT NOT NULL,
    rate                NUMERIC(14,6) NOT NULL CHECK (rate > 0),
    provider_updated_at TIMESTAMPTZ NOT NULL,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    source              TEXT NOT NULL DEFAULT 'api',   -- 'api' or 'synthetic'
    UNIQUE (base, quote, provider_updated_at)
);
CREATE INDEX idx_fx_rates_pair_time ON fx_rates (base, quote, provider_updated_at DESC);

-- Which rate alerts were already sent (so nothing alerts twice).
CREATE TABLE alerts_log (
    kind                TEXT NOT NULL CHECK (kind IN ('move', 'budget')),
    base                TEXT NOT NULL,
    quote               TEXT NOT NULL,
    provider_updated_at TIMESTAMPTZ NOT NULL,
    metric              NUMERIC(10,4) NOT NULL,        -- % move, or % over budget
    alerted_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, base, quote, provider_updated_at)
);

-- System health alerts (max one per kind per day).
CREATE TABLE system_alerts (
    kind       TEXT NOT NULL,
    day        DATE NOT NULL,
    detail     TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, day)
);

-- Filled by the n8n error workflow.
CREATE TABLE workflow_errors (
    id            SERIAL PRIMARY KEY,
    workflow_name TEXT,
    node_name     TEXT,
    message       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Each observation compared with the one before it (window functions).
CREATE VIEW fx_moves AS
SELECT base, quote, provider_updated_at, rate,
       LAG(rate) OVER w                                     AS prev_rate,
       round(100 * (rate / LAG(rate) OVER w - 1), 4)        AS pct_change,
       avg(rate) OVER (PARTITION BY base, quote
                       ORDER BY provider_updated_at
                       ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS avg_prev_7
FROM fx_rates
WINDOW w AS (PARTITION BY base, quote ORDER BY provider_updated_at);

-- Starter configuration. EXAMPLE NUMBERS: replace them with your company's real ones.
INSERT INTO watch_pairs (base, quote, threshold_pct) VALUES ('EUR','TND',0.5), ('USD','TND',0.5);
INSERT INTO import_exposure (label, currency, monthly_amount) VALUES
    ('Supplier A (EUR invoices)', 'EUR', 10000),
    ('Supplier B (USD invoices)', 'USD', 4000);
INSERT INTO budget_rates (base, quote, budget_rate, tolerance_pct) VALUES
    ('EUR','TND',3.30,2), ('USD','TND',2.85,2);
