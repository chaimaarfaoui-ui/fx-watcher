#!/usr/bin/env python3
"""Generate the n8n workflow JSON files from the SQL files in sql/.

Why: the SQL is the single source of truth. Edit sql/*.sql, run this script, re-import the workflow.
A test checks that the committed n8n/*.json files match what this script produces.

    python scripts/build_workflows.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAT = "REPLACE_WITH_YOUR_CHAT_ID"
PG = {"postgres": {"id": "", "name": "FX DB"}}
TG = {"telegramApi": {"id": "", "name": "Telegram bot"}}
SMTP = {"smtp": {"id": "", "name": "SMTP"}}
EMAIL = "REPLACE_WITH_YOUR_EMAIL"   # used as sender and recipient; set it in the node, never commit your address


def sql(name: str) -> str:
    """Read a SQL file and drop full-line comments."""
    lines = (ROOT / "sql" / name).read_text(encoding="utf-8").splitlines()
    return "\n".join(l for l in lines if not l.strip().startswith("--")).strip()


def node(id_, name, type_, ver, pos, params, **extra):
    n = {"id": id_, "name": name, "type": type_, "typeVersion": ver, "position": pos, "parameters": params}
    n.update(extra)
    return n


def cron(id_, name, expr, pos=(0, 200)):
    return node(id_, name, "n8n-nodes-base.scheduleTrigger", 1.2, list(pos),
                {"rule": {"interval": [{"field": "cronExpression", "expression": expr}]}})


def pg_query(id_, name, query, pos, replacement=None):
    options = {"queryReplacement": replacement} if replacement else {}
    return node(id_, name, "n8n-nodes-base.postgres", 2.5, list(pos),
                {"operation": "executeQuery", "query": query, "options": options}, credentials=PG)


def telegram(id_, name, text, pos):
    return node(id_, name, "n8n-nodes-base.telegram", 1.2, list(pos),
                {"chatId": CHAT, "text": text, "additionalFields": {"appendAttribution": False}},
                credentials=TG)


def notify(id_, name, subject, body, pos, channel, emoji=""):
    """The delivery box: an email (default) or a Telegram message. Same text, different channel."""
    if channel == "telegram":
        return telegram(id_, name, "=" + (emoji + " " if emoji else "") + body, pos)
    return node(id_, name, "n8n-nodes-base.emailSend", 2.1, list(pos),
                {"fromEmail": EMAIL, "toEmail": EMAIL, "subject": "=" + subject,
                 "emailFormat": "text", "text": "=" + body, "options": {}},
                credentials=SMTP)


def link(*names):
    """Chain nodes in a straight line."""
    return {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(names, names[1:])}


def workflow(name, nodes, connections):
    return {"name": name, "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1"}}


def build_all(channel: str = "email") -> dict[str, dict]:
    assert channel in ("email", "telegram")
    out = {}

    out["fx_collector.json"] = workflow("FX collector", [
        cron("a1", "Every 6 hours", "0 */6 * * *"),
        pg_query("a2", "Which currencies to watch?", "SELECT DISTINCT base FROM watch_pairs WHERE active", (240, 200)),
        node("a3", "Call the rates API", "n8n-nodes-base.httpRequest", 4.2, [480, 200],
             {"method": "GET", "url": "=https://open.er-api.com/v6/latest/{{ $json.base }}",
              "options": {"timeout": 15000}},
             retryOnFail=True, maxTries=3, waitBetweenTries=3000),
        node("a4", "Keep only what we need", "n8n-nodes-base.set", 3.4, [720, 200],
             {"assignments": {"assignments": [
                 {"id": "s1", "name": "base", "value": "={{ $json.base_code }}", "type": "string"},
                 {"id": "s2", "name": "updated_unix", "value": "={{ $json.time_last_update_unix }}", "type": "number"},
                 {"id": "s3", "name": "rates_json", "value": "={{ JSON.stringify($json.rates) }}", "type": "string"}]},
              "options": {}}),
        pg_query("a5", "Save to database", sql("collector_insert.sql"), (960, 200),
                 "={{ [$json.base, $json.rates_json, $json.updated_unix] }}"),
    ], link("Every 6 hours", "Which currencies to watch?", "Call the rates API",
            "Keep only what we need", "Save to database"))

    # two independent branches from one trigger: rate moves, and budget crossings
    t = "Every 6 hours (30 min after collector)"
    out["fx_alerts.json"] = workflow("FX alerts", [
        cron("b1", t, "30 */6 * * *"),
        pg_query("b2", "New big moves?", sql("alert_moves.sql"), (260, 100)),
        notify("b3", "Alert: rate moved",
               "FX alert: {{ $json.base }}/{{ $json.quote }} moved {{ $json.pct_change }}%",
               "{{ $json.base }}/{{ $json.quote }} moved {{ $json.pct_change }}%\n"
               "{{ $json.prev_rate }} -> {{ $json.rate }}\n"
               "Monthly {{ $json.base }} exposure ({{ $json.monthly_exposure }}) now costs "
               "{{ $json.extra_monthly_cost }} {{ $json.quote }} more per month (negative = cheaper).\n"
               "Rates by exchangerate-api.com", (520, 100), channel, "\U0001F4B1"),
        pg_query("b4", "Budget crossed?", sql("alert_budget.sql"), (260, 300)),
        notify("b5", "Alert: over budget",
               "FX alert: {{ $json.base }}/{{ $json.quote }} is above budget",
               "{{ $json.base }}/{{ $json.quote }} is {{ $json.pct_over_budget }}% above your budget rate "
               "({{ $json.budget_rate }}).\nNow: {{ $json.rate }}\n"
               "Extra cost vs budget: {{ $json.extra_vs_budget }} {{ $json.quote }} per month "
               "on {{ $json.monthly_exposure }} {{ $json.base }}.\nRates by exchangerate-api.com",
               (520, 300), channel, "\U0001F3AF"),
    ], {
        t: {"main": [[{"node": "New big moves?", "type": "main", "index": 0},
                      {"node": "Budget crossed?", "type": "main", "index": 0}]]},
        **link("New big moves?", "Alert: rate moved"),
        **link("Budget crossed?", "Alert: over budget"),
    })

    out["fx_weekly_digest.json"] = workflow("FX weekly digest", [
        cron("c1", "Every Monday 08:00", "0 8 * * 1"),
        pg_query("c2", "Build the summary", sql("weekly_digest.sql"), (260, 200)),
        notify("c3", "Send summary", "FX weekly summary", "{{ $json.message }}", (520, 200), channel, "\U0001F4CA"),
    ], {"Every Monday 08:00": {"main": [[{"node": "Build the summary", "type": "main", "index": 0}]]},
        "Build the summary": {"main": [[{"node": "Send summary", "type": "main", "index": 0}]]}})

    out["fx_health.json"] = workflow("FX health check", [
        cron("d1", "Every 6 hours (45 min)", "45 */6 * * *"),
        pg_query("d2", "Is data fresh?", sql("alert_health.sql"), (260, 200)),
        notify("d3", "Alert: data problem", "FX Watcher: data problem", "FX data problem: {{ $json.detail }}",
               (520, 200), channel, "\u26a0\ufe0f"),
    ], link("Every 6 hours (45 min)", "Is data fresh?", "Alert: data problem"))

    out["fx_error_handler.json"] = workflow("FX error handler", [
        node("e1", "Error Trigger", "n8n-nodes-base.errorTrigger", 1, [0, 200], {}),
        pg_query("e2", "Log error in DB",
                 "INSERT INTO workflow_errors (workflow_name, node_name, message) VALUES ($1, $2, $3)", (260, 100),
                 "={{ [$json.workflow.name, $json.execution.lastNodeExecuted, $json.execution.error.message] }}"),
        notify("e3", "Alert: workflow failed", "FX Watcher: workflow failed",
               "Workflow failed: {{ $json.workflow.name }}\nNode: {{ $json.execution.lastNodeExecuted }}\n"
               "{{ $json.execution.error.message }}", (260, 300), channel, "\u26a0\ufe0f"),
    ], {"Error Trigger": {"main": [[{"node": "Log error in DB", "type": "main", "index": 0},
                                    {"node": "Alert: workflow failed", "type": "main", "index": 0}]]}})
    return out


def check_connections(wf: dict) -> None:
    names = {n["name"] for n in wf["nodes"]}
    for src, c in wf["connections"].items():
        assert src in names, f"unknown source node {src}"
        for branch in c["main"]:
            for t in branch:
                assert t["node"] in names, f"unknown target node {t['node']}"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Generate the n8n workflow files from the SQL files.")
    ap.add_argument("--channel", choices=["email", "telegram"], default="email",
                    help="how alerts are delivered (default: email)")
    args = ap.parse_args()
    (ROOT / "n8n").mkdir(exist_ok=True)
    for fname, wf in build_all(args.channel).items():
        check_connections(wf)
        (ROOT / "n8n" / fname).write_text(json.dumps(wf, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote n8n/" + fname + " (" + args.channel + ")")
