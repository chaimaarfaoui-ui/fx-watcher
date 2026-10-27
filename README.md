# FX Watcher

Automated exchange-rate monitoring for a business that pays suppliers in EUR/USD but earns in TND.
It collects daily rates, stores them in PostgreSQL, and emails what a rate move **costs in dinars**.

**Stack:** n8n · Python · PostgreSQL · REST API (open.er-api.com)

## What it does

- **Collects** EUR/TND and USD/TND rates every 6 hours (free API, with retries)
- **Stores** them in PostgreSQL with constraints that block duplicates and bad data
- **Alerts by email** when a rate moves past a threshold, with the monthly cost impact
- **Compares** against a budget rate and flags when reality drifts from the plan
- **Sends a weekly summary** (Mondays, 08:00)
- **Monitors itself:** a health check warns if data goes stale, and an error handler logs and reports any failed workflow

Running a workflow twice never stores a rate twice or sends an alert twice (idempotent).

## Architecture

```mermaid
flowchart LR
    A[Exchange-rate API] -->|every 6h| B[n8n collector]
    B --> C[(PostgreSQL)]
    C --> D[Move and budget alerts]
    C --> E[Weekly digest]
    C --> F[Health check]
    D --> M[Email]
    E --> M
    F --> M
    X[Error handler] --> C
    X --> M
```

Business settings (watched pairs, thresholds, supplier amounts, budget rates) live in database tables,
so they can be changed with plain SQL and no code changes. The amounts in `schema.sql` are examples.

## Project structure


The n8n workflow files are generated from the SQL files by `scripts/build_workflows.py`,
so the SQL stays the single source of truth.

## Run it

Requirements: PostgreSQL 16, Python 3.10+, n8n.

```bash
git clone https://github.com/chaimaarfaoui-ui/fx-watcher.git
cd fx-watcher
cp .env.example .env              # edit the values
```

1. Create a Postgres user `fx` and a database `fxwatch`, then load the schema:
   ```bash
   psql -U fx -h localhost -d fxwatch -f sql/schema.sql
   ```
2. Install dependencies and set the connection string:
   ```bash
   pip install "psycopg[binary]" pytest
   export DATABASE_URL=postgresql://fx:YOUR_PASSWORD@localhost:5432/fxwatch   # PowerShell: $env:DATABASE_URL="..."
   ```
3. Run the Python collector once, then the tests:
   ```bash
   python scripts/fetch_rates.py
   pytest
   ```
4. In n8n, import the files from `n8n/`, attach your Postgres and SMTP credentials, and put your email address in the email nodes.
   Publish **FX error handler** first, then set it as the *Error workflow* of the other four and publish them.

A `docker-compose.yml` (n8n + Postgres) is included as an alternative setup. It is untested.

## Testing

21 automated tests pass: 4 unit tests (API parsing) and 17 database tests covering the schema constraints,
duplicate protection, alert logic and the weekly summary. I also ran the full flow against the live API:
real rates stored, a real alert email sent with the correct monthly cost, and a repeat run that added nothing.