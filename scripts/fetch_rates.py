#!/usr/bin/env python3
"""Fetch exchange rates from open.er-api.com and store them in PostgreSQL.

This is the Python twin of the n8n collector workflow: same job, same result.
Use it to learn the API, to backfill, or when n8n is not running.

    python scripts/fetch_rates.py
    python scripts/fetch_rates.py --api http://localhost:9999/v6/latest   # test against a mock

Rates by Exchange Rate API: https://www.exchangerate-api.com  (attribution required by their terms)
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

DSN = os.environ.get("DATABASE_URL", "postgresql://fx:fx@localhost:5432/fxwatch")
DEFAULT_API = "https://open.er-api.com/v6/latest"


class ApiError(Exception):
    pass


def parse_response(data: dict, quotes: list[str]) -> tuple[datetime, dict[str, Decimal]]:
    """Turn the API JSON into (provider update time, {quote: rate}). Fails loudly on bad data."""
    if data.get("result") != "success":
        raise ApiError(f"API reported an error: {data.get('error-type', data)}")
    rates = data.get("rates") or {}
    updated = datetime.fromtimestamp(data["time_last_update_unix"], tz=timezone.utc)
    out = {}
    for q in quotes:
        if q not in rates:
            raise ApiError(f"currency {q} is missing from the response")
        out[q] = Decimal(str(rates[q]))
    return updated, out


def fetch_json(url: str, tries: int = 3, wait: float = 2.0) -> dict:
    """GET a URL and return parsed JSON, retrying with a growing pause on failure."""
    last = None
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            print(f"  attempt {attempt}/{tries} failed: {exc}", file=sys.stderr)
            if attempt < tries:
                time.sleep(wait * attempt)
    raise ApiError(f"giving up on {url}: {last}")


def main() -> None:
    import psycopg  # imported here so the parsing tests need no database driver

    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=DEFAULT_API)
    args = ap.parse_args()

    new_rows, failures = 0, []
    with psycopg.connect(DSN, autocommit=True) as conn:   # each insert is saved immediately
        pairs = conn.execute(
            "SELECT base, array_agg(quote) FROM watch_pairs WHERE active GROUP BY base ORDER BY base"
        ).fetchall()
        for base, quotes in pairs:
            try:
                data = fetch_json(f"{args.api}/{base}")
                updated, rates = parse_response(data, quotes)
            except ApiError as exc:                       # one bad currency must not block the others
                print(f"FAILED {base}: {exc}", file=sys.stderr)
                failures.append(base)
                continue
            for quote, rate in rates.items():
                cur = conn.execute(
                    """INSERT INTO fx_rates (base, quote, rate, provider_updated_at)
                       VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    (base, quote, rate, updated),
                )
                new_rows += cur.rowcount
                print(f"{base}/{quote} = {rate}  (provider update {updated:%Y-%m-%d %H:%M} UTC)"
                      + ("" if cur.rowcount else "  [already stored]"))
    print(f"done: {new_rows} new row(s)")
    if failures:
        sys.exit(f"failed for: {', '.join(failures)}")   # non-zero exit so n8n / cron notice


if __name__ == "__main__":
    main()
