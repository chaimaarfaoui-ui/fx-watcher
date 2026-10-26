"""Integration tests: the exact SQL that n8n runs, executed on a real PostgreSQL."""
import json
from pathlib import Path

import build_workflows as bw

ROOT = Path(__file__).resolve().parent.parent


def run(conn, filename):
    return conn.execute(bw.sql(filename)).fetchall()


def add_rate(conn, base, rate, days_ago, source="api", quote="TND"):
    conn.execute(
        """INSERT INTO fx_rates (base, quote, rate, provider_updated_at, source)
           VALUES (%s, %s, %s, date_trunc('day', now()) - make_interval(days => %s), %s)""",
        (base, quote, rate, days_ago, source),
    )


def series(conn, base, rates):
    """rates are oldest -> newest, the newest is 'yesterday' (days_ago = 1)."""
    for i, r in enumerate(rates):
        add_rate(conn, base, r, len(rates) - i)


# ---------- rate-move alerts ----------
def test_move_alert_fires_once_with_business_impact(db):
    series(db, "EUR", [3.35] * 9 + [3.40])          # +1.49%
    first = run(db, "alert_moves.sql")
    assert len(first) == 1
    base, quote, rate, prev, pct, exposure, extra = first[0]
    assert (base, quote) == ("EUR", "TND") and float(pct) > 1.4
    assert float(exposure) == 10000 and float(extra) == round(10000 * (3.40 - 3.35))
    assert run(db, "alert_moves.sql") == []          # already alerted


def test_small_move_does_not_alert(db):
    series(db, "EUR", [3.350, 3.351, 3.352, 3.353])   # ~0.03% per step
    assert run(db, "alert_moves.sql") == []


def test_decrease_also_alerts_with_negative_cost(db):
    series(db, "USD", [2.90] * 5 + [2.85])
    rows = run(db, "alert_moves.sql")
    assert len(rows) == 1 and float(rows[0][4]) < 0 and float(rows[0][6]) < 0


def test_inactive_pair_is_ignored(db):
    db.execute("UPDATE watch_pairs SET active = FALSE WHERE base = 'EUR'")
    series(db, "EUR", [3.35] * 5 + [3.45])
    assert run(db, "alert_moves.sql") == []


# ---------- budget alerts ----------
def test_budget_alert_only_on_crossing(db):
    # budget 3.30, tolerance 2% -> limit 3.366
    series(db, "EUR", [3.35, 3.35, 3.35, 3.40])
    rows = run(db, "alert_budget.sql")
    assert len(rows) == 1
    base, quote, rate, budget, pct_over, exposure, extra = rows[0]
    assert float(budget) == 3.30 and float(pct_over) > 3 and float(extra) == round(10000 * (3.40 - 3.30))
    assert run(db, "alert_budget.sql") == []                      # same observation: silent
    add_rate(db, "EUR", 3.41, 0)                                  # still above budget, not a new crossing
    assert run(db, "alert_budget.sql") == []


def test_no_budget_alert_inside_tolerance(db):
    series(db, "EUR", [3.30, 3.31, 3.32, 3.33])
    assert run(db, "alert_budget.sql") == []


# ---------- freshness watchdog ----------
def test_stale_data_alerts_once_per_day(db):
    add_rate(db, "EUR", 3.35, 4)                                  # 4 days old
    rows = run(db, "alert_health.sql")
    assert len(rows) == 1 and "hours ago" in rows[0][0]
    assert run(db, "alert_health.sql") == []


def test_fresh_data_is_silent(db):
    add_rate(db, "EUR", 3.35, 0)
    assert run(db, "alert_health.sql") == []


def test_no_data_at_all_alerts(db):
    rows = run(db, "alert_health.sql")
    assert rows and "No API data" in rows[0][0]


def test_synthetic_data_does_not_hide_a_dead_collector(db):
    add_rate(db, "EUR", 3.35, 0, source="synthetic")
    assert len(run(db, "alert_health.sql")) == 1


# ---------- weekly digest ----------
def test_digest_mentions_pairs_budget_and_attribution(db):
    series(db, "EUR", [3.30 + i * 0.002 for i in range(40)])
    series(db, "USD", [2.90 + i * 0.001 for i in range(40)])
    (message,) = run(db, "weekly_digest.sql")[0]
    assert "EUR/TND" in message and "USD/TND" in message
    assert "budget 3.3000" in message and "7d: +" in message
    assert "exchangerate-api.com" in message


def test_digest_with_no_data_does_not_crash(db):
    assert "No data yet" in run(db, "weekly_digest.sql")[0][0]


# ---------- the SQL that n8n uses to save rates ----------
def test_collector_insert_is_idempotent_and_respects_config(db):
    db.execute("PREPARE ins(text, text, bigint) AS " + bw.sql("collector_insert.sql"))
    call = "EXECUTE ins('EUR', '{\"TND\": 3.4, \"USD\": 1.17}', 1759536000)"
    assert db.execute(call).rowcount == 1             # only TND is watched for EUR, USD is ignored
    assert db.execute(call).rowcount == 0             # same provider update: nothing new
    assert db.execute("SELECT count(*) FROM fx_rates").fetchone()[0] == 1


# ---------- workflow files ----------
def test_committed_workflows_match_the_sql_files():
    for fname, expected in bw.build_all().items():
        committed = json.loads((ROOT / "n8n" / fname).read_text(encoding="utf-8"))
        assert committed == expected, f"{fname} is out of date: run python scripts/build_workflows.py"


def test_every_workflow_has_valid_connections():
    for wf in bw.build_all().values():
        bw.check_connections(wf)


def test_both_delivery_channels_build_valid_workflows():
    for channel, node_type in (("email", "emailSend"), ("telegram", "telegram")):
        built = bw.build_all(channel)
        for wf in built.values():
            bw.check_connections(wf)
        used = {n["type"].split(".")[-1] for wf in built.values() for n in wf["nodes"]}
        assert node_type in used
        other = "telegram" if channel == "email" else "emailSend"
        assert other not in used


def test_no_personal_email_is_committed():
    text = "".join((ROOT / "n8n" / f).read_text(encoding="utf-8") for f in bw.build_all())
    assert "REPLACE_WITH_YOUR_EMAIL" in text and "@gmail.com" not in text
