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

## Demo

**Scheduled runs.** The collector starts on the hour (12:00, 18:00) without anyone clicking.
It runs every 6 hours while n8n is running.

![Collector executions](docs/collector-scheduled-runs.png)

**Email alert.** A test alert with a lowered threshold: the rate change and what it costs per month in TND.

![Alert email](docs/alert-email.png)

**Failure handling.** During a real network outage the error handler logged the failure in the database
(green) but could not send its email (red), because the network itself was down. The next scheduled runs succeeded.

![Error handler during an outage](docs/error-handler-outage.png)

**Tests.** All 21 tests pass: 4 unit tests and 17 against a real PostgreSQL database.

![21 tests passing](docs/tests-passing.png)

## Project structure

```
sql/        schema, alert queries, weekly digest, learning queries
scripts/    fetch_rates.py (Python collector), build_workflows.py, demo_history.py
n8n/        5 importable workflows
tests/      4 unit tests + 17 database tests
docs/       screenshots
```

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
   python -m pytest
   ```
4. In n8n, import the files from `n8n/`, attach your Postgres and SMTP credentials, and put your email address in the email nodes.
   Publish **FX error handler** first, then set it as the *Error workflow* of the other four and publish them.

A `docker-compose.yml` (n8n + Postgres) is included as an alternative setup. It is untested.

## Limitations

- Self-hosted n8n only runs while the machine it lives on is on, so there are gaps when it is off.
- Email alerts cannot be sent when the network is down. The failure is still logged in `workflow_errors`.
