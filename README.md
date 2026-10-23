# FX Watcher: exchange-rate risk monitoring for a business that pays in EUR/USD

Watches TND exchange rates and tells a business **what rate moves cost it in dinars**, against the
budget it planned. Built with **n8n, a public REST API, Python and PostgreSQL**.

## What it does

| Feature | Example output |
|---|---|
| **Move alert** | 💱 EUR/TND moved 1.33% (3.2998 → 3.3436). Monthly EUR exposure (10000) now costs 438 TND more per month. |
| **Budget alert** (fires when the rate crosses your budget + tolerance) | 🎯 EUR/TND is 3.1% above your budget rate (3.30). Extra cost vs budget: 1,030 TND per month. |
| **Weekly summary** (Monday 08:00, email (or Telegram)) | `EUR/TND 3.3436 \| 7d: +1.80% \| 30d range position: 100% \| budget 3.3000: +1.3% (+436 TND per month)` |
| **Freshness watchdog** | ⚠️ Latest API rate is from 2026-10-01 00:00 UTC (about 79 hours ago) |
| **Error handler** | Any failed workflow is logged in `workflow_errors` and alerted |

The business problem: a company that pays suppliers in EUR or USD but earns in TND is exposed to every
move. Finance teams plan with a **budget rate** and need to know when reality drifts from it, and what that
costs, while there is still time to act (negotiate, buy currency earlier, adjust prices).

## Architecture

```mermaid
flowchart LR
    A[open.er-api.com<br/>free, no key] -->|every 6h, 3 retries| B[n8n collector]
    B --> C[(PostgreSQL)]
    C --> D[n8n alerts<br/>moves + budget]
    C --> E[n8n weekly digest]
    C --> F[n8n health check]
    D --> T[Telegram]
    E --> T
    E -.optional.-> M[Email]
    F --> T
    X[n8n error handler] --> C
    X --> T
    G[config tables:<br/>watch_pairs, import_exposure, budget_rates] --> C
```

**Make it yours without touching code.** Everything business-specific is a table row:

```sql
INSERT INTO watch_pairs (base, quote, threshold_pct) VALUES ('GBP', 'TND', 0.5);
UPDATE import_exposure SET monthly_amount = 25000 WHERE label LIKE 'Supplier A%';
UPDATE budget_rates SET budget_rate = 3.28, tolerance_pct = 1.5 WHERE base = 'EUR';
```
The seeded numbers are **examples**. Replace them with the company's real figures.

## Project layout

```
sql/schema.sql            tables, constraints, view (window functions)
sql/alert_moves.sql       rate-move alert (claims alerts atomically, never twice)
sql/alert_budget.sql      budget-crossing alert
sql/alert_health.sql      stale-data watchdog
sql/weekly_digest.sql     ready-to-send summary message
sql/collector_insert.sql  how n8n saves rates
sql/queries.sql           learning queries (CTEs, windows, data-quality checks)
scripts/fetch_rates.py    Python version of the collector
scripts/demo_history.py   synthetic history for testing (marked source='synthetic')
scripts/build_workflows.py  generates n8n/*.json FROM the sql files
n8n/                      5 importable workflows
tests/                    unit tests + 15 database integration tests
```

`sql/` is the **single source of truth**. Edit a query, run `python scripts/build_workflows.py`,
re-import the workflow. A test fails if the committed workflows drift from the SQL.

## Learning path (do it in this order)

**Stage 1: understand the API (15 min).**
```bash
curl https://open.er-api.com/v6/latest/EUR
```
Find `result`, `base_code`, `time_last_update_unix`, and inside `rates` the `TND` value. **Check that TND is
there.** The API is free and needs no key, updates **once a day**, is rate-limited, and **requires
attribution to exchangerate-api.com** (alert texts include it).

**Stage 2: start the stack.**
```bash
cp .env.example .env
docker compose up -d
```
Open http://localhost:5678 and create the n8n owner account.

**Stage 3: get data without waiting weeks.**
```bash
pip install "psycopg[binary]" pytest
export DATABASE_URL=postgresql://fx:change-me@localhost:5432/fxwatch   # match .env
python scripts/demo_history.py --days 60 --jump 1.2     # SYNTHETIC
python scripts/fetch_rates.py                            # real rates (needs internet)
```
Remove demo data before real use: `DELETE FROM fx_rates WHERE source = 'synthetic';`

**Stage 4: read the SQL.** Run `sql/queries.sql` query by query, then read the five alert files. They show
`DISTINCT ON`, CTEs, window functions (`LAG`, rolling `avg`), `INSERT ... ON CONFLICT ... RETURNING`
used as an atomic "claim", and `generate_series` for gap detection.

**Stage 5: n8n.**
```bash
for f in fx_collector fx_alerts fx_weekly_digest fx_health fx_error_handler; do
  docker compose exec n8n n8n import:workflow --input=/workflows/$f.json
done
```
Create a **Postgres** credential (host `db`, user, password and database from `.env`) and select it on every
Postgres node. Run each workflow with **Execute workflow** and read the output between nodes. Then open the
*Settings* of the first four workflows and set **Error workflow** to *FX error handler*.

**Stage 6: delivery channel (email by default).** The workflows send **email** through n8n's Send Email (SMTP) box.
For Gmail: turn on 2-Step Verification on the Google account, create an **app password** (Google account, Security,
App passwords), then in n8n create an **SMTP** credential: host `smtp.gmail.com`, port `465`, SSL/TLS on, user = your Gmail
address, password = the app password (never your normal password). In each email box, replace `REPLACE_WITH_YOUR_EMAIL`
with your address and select the SMTP credential. Keep your address out of the repository.
Prefer Telegram? Run `python scripts/build_workflows.py --channel telegram`, then follow @BotFather to create a bot,
add a Telegram credential in n8n, and put your chat id in the Telegram boxes. Use the channel your recipient already uses.

**To test an alert immediately:** `UPDATE watch_pairs SET threshold_pct = 0.1; DELETE FROM alerts_log;`

## Design decisions worth talking about

- **Idempotent collection.** The API updates daily but we poll every 6h. `UNIQUE (base, quote, provider_updated_at)`
  plus `ON CONFLICT DO NOTHING` makes re-fetching harmless.
- **Alerts fire once.** Alerts are written to `alerts_log` with `INSERT ... ON CONFLICT DO NOTHING RETURNING`, so
  only new ones come back. The budget alert fires on the **crossing**, not every day the rate stays high.
- **Monitoring the monitor.** The watchdog catches a dead collector or API. Synthetic data cannot hide it,
  because it only looks at `source = 'api'`.
- **Fails loudly, not fully.** A bad currency raises an error but does not block the others, and the script exits
  non-zero so a scheduler notices. The HTTP node retries 3 times.
- **Exact decimals** (`NUMERIC` / `Decimal`), never float, for rates and money.
- **Configuration in tables**, so adding a currency or changing a budget needs no deployment.
- **Tests run the exact SQL n8n runs**, in a throwaway schema.

## Tests

```bash
pytest                       # 4 unit tests (always) + 15 database tests (need DATABASE_URL)
```

## What was tested, and what was not

Tested on PostgreSQL 16: the schema, every alert and digest query, idempotent collection (the same SQL n8n
uses), `fetch_rates.py` (parsing, idempotency, partial failure, retries), all 19 tests passing.
The API was **mocked**, because the live API could not be reached from my test environment.

**Not tested:** the live API call, the Docker Compose file, and importing/running the n8n workflows
(I could not run n8n). The workflow JSON is generated and checked for valid connections, but n8n node
versions differ between releases. If an import or node shows an error, fix it from the message, then update
`scripts/build_workflows.py` so the repo stays in sync.

## Limits (honest)

- Rates are daily **mid-market** rates, not what your bank charges. A bank's buy/sell rates and fees differ,
  so treat costs as estimates. (A per-bank spread setting is a good extension.)
- Monitoring, not trading: do not use it for intraday decisions. This is information, not financial advice.
- The cost estimate assumes the same monthly amount every month and only covers pairs quoted in TND.
- TND moves slowly, so tune `threshold_pct` and `tolerance_pct` after seeing real data.
- A free third-party API has no availability guarantee. The watchdog tells you when it fails.

## Next steps

1. Add an **LLM step**: send the alert numbers to an LLM API and ask for a two-line French explanation for a non-technical manager.
2. Add a **dashboard** (Metabase) on `fx_moves`.
3. Add a **recipient/channel table** so each person gets alerts on the channel they use.

## CV bullet

> Built an automated FX-risk monitor (n8n, Python, PostgreSQL, REST API): idempotent scheduled ingestion with
> retries, window-function analytics, budget-vs-actual and rate-move alerts translated into monthly TND cost,
> weekly reporting, a data-freshness watchdog and a global error handler; covered by 19 automated tests.
#   f x - w a t c h e r  
 