#!/usr/bin/env python3
"""Fill the database with SYNTHETIC rate history so you can test the dashboard and alerts
before you have weeks of real data. Rows are marked source='synthetic'.

    python scripts/demo_history.py --days 60 --jump 1.2

The last day of EUR/TND jumps by --jump percent so the alert has something to catch.
Remove it before real use:  DELETE FROM fx_rates WHERE source = 'synthetic';
"""
import argparse
import os
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg

DSN = os.environ.get("DATABASE_URL", "postgresql://fx:fx@localhost:5432/fxwatch")
START = {"EUR": 3.35, "USD": 2.90}  # made-up starting levels


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--jump", type=float, default=1.2, help="% jump on the last day of EUR/TND")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    with psycopg.connect(DSN) as conn:
        for base, level in START.items():
            rate = level
            for i in range(a.days, 0, -1):          # oldest -> yesterday
                rate *= 1 + rng.gauss(0, 0.0015)    # ~0.15% daily noise
                if base == "EUR" and i == 1:
                    rate *= 1 + a.jump / 100
                conn.execute(
                    """INSERT INTO fx_rates (base, quote, rate, provider_updated_at, source)
                       VALUES (%s, 'TND', %s, %s, 'synthetic') ON CONFLICT DO NOTHING""",
                    (base, Decimal(str(round(rate, 6))), today - timedelta(days=i)),
                )
    print(f"inserted {a.days} synthetic days for {', '.join(START)} (last EUR day jumps {a.jump}%)")


if __name__ == "__main__":
    main()
