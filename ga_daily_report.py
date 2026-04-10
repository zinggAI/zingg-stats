#!/usr/bin/env python3
"""
Zingg Google Analytics Daily Report → Slack

Fetches yesterday's GA4 metrics and sends a summary to #repo-stats on Slack.

Setup:
  pip install google-analytics-data google-auth requests

  Add to config.py:
    GA_PROPERTY_ID = "123456789"
    GA_CREDENTIALS = "~/.zingg/ga_credentials.json"

Usage:
  python ga_daily_report.py --config /path/to/config.py

Cron (9am daily):
  0 9 * * * /path/to/venv/bin/python /path/to/ga_daily_report.py --config ~/.zingg/config.py >> ~/zingg-stats/stats.log 2>&1
"""

import argparse
import importlib.util
import os
import requests
from datetime import datetime, timedelta, timezone

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
    OrderBy,
)
from google.oauth2 import service_account


# ── Config loader ─────────────────────────────────────────────────────────────

def load_config(config_path):
    spec = importlib.util.spec_from_file_location("config", config_path)
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    return cfg


# ── GA4 client ────────────────────────────────────────────────────────────────

def get_ga_client(cfg):
    credentials = service_account.Credentials.from_service_account_file(
        os.path.expanduser(cfg.GA_CREDENTIALS),
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )
    return BetaAnalyticsDataClient(credentials=credentials)


def run_report(client, property_id, dimensions, metrics, date_range, order_bys=None, limit=10):
    """Run a GA4 report and return rows as a list of dicts."""
    request = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        date_ranges=[DateRange(start_date=date_range[0], end_date=date_range[1])],
        order_bys=order_bys or [],
        limit=limit,
    )
    response = client.run_report(request)
    rows = []
    for row in response.rows:
        entry = {}
        for i, dim in enumerate(dimensions):
            entry[dim] = row.dimension_values[i].value
        for i, met in enumerate(metrics):
            entry[met] = row.metric_values[i].value
        rows.append(entry)
    return rows


# ── Data fetchers ─────────────────────────────────────────────────────────────

def fetch_overview(client, property_id, date_range):
    """Fetch top-level metrics: sessions, users, pageviews, bounce rate, avg duration."""
    rows = run_report(
        client, property_id,
        dimensions=[],
        metrics=[
            "sessions",
            "totalUsers",
            "newUsers",
            "screenPageViews",
            "bounceRate",
            "averageSessionDuration",
        ],
        date_range=date_range,
        limit=1,
    )
    return rows[0] if rows else {}


def fetch_top_pages(client, property_id, date_range, limit=10):
    """Top pages by pageviews."""
    return run_report(
        client, property_id,
        dimensions=["pagePath", "pageTitle"],
        metrics=["screenPageViews", "totalUsers"],
        date_range=date_range,
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"), desc=True)],
        limit=limit,
    )


def fetch_top_sources(client, property_id, date_range, limit=10):
    """Top traffic sources."""
    return run_report(
        client, property_id,
        dimensions=["sessionSource", "sessionMedium"],
        metrics=["sessions", "totalUsers"],
        date_range=date_range,
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=limit,
    )


def fetch_top_countries(client, property_id, date_range, limit=5):
    """Top countries by sessions."""
    return run_report(
        client, property_id,
        dimensions=["country"],
        metrics=["sessions", "totalUsers"],
        date_range=date_range,
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=limit,
    )


def fetch_devices(client, property_id, date_range):
    """Sessions split by device category."""
    return run_report(
        client, property_id,
        dimensions=["deviceCategory"],
        metrics=["sessions"],
        date_range=date_range,
    )


# ── Slack message builder ─────────────────────────────────────────────────────

def fmt_duration(seconds_str):
    """Convert seconds string to mm:ss."""
    try:
        s = int(float(seconds_str))
        return f"{s // 60}m {s % 60}s"
    except Exception:
        return seconds_str


def fmt_pct(val_str):
    try:
        return f"{float(val_str) * 100:.1f}%"
    except Exception:
        return val_str


def build_message(overview, top_pages, top_sources, top_countries, devices, date_label, cfg):
    lines = [
        f"*Zingg Google Analytics — {date_label}*",
        f"_Property ID: {cfg.GA_PROPERTY_ID}_",
        "",
        "*Overview*",
        f"• Sessions: *{int(overview.get('sessions', 0)):,}*",
        f"• Total Users: *{int(overview.get('totalUsers', 0)):,}*",
        f"• New Users: *{int(overview.get('newUsers', 0)):,}*",
        f"• Page Views: *{int(overview.get('screenPageViews', 0)):,}*",
        f"• Bounce Rate: *{fmt_pct(overview.get('bounceRate', '0'))}*",
        f"• Avg Session Duration: *{fmt_duration(overview.get('averageSessionDuration', '0'))}*",
    ]

    if devices:
        device_parts = [f"{r['deviceCategory']}: {int(r['sessions']):,}" for r in devices]
        lines += ["", f"*Devices*  {' · '.join(device_parts)}"]

    if top_sources:
        lines += ["", "*Top Traffic Sources*"]
        for r in top_sources:
            source = f"{r['sessionSource']} / {r['sessionMedium']}"
            lines.append(f"• {source}: {int(r['sessions']):,} sessions ({int(r['totalUsers']):,} users)")

    if top_pages:
        lines += ["", "*Top Pages*"]
        for r in top_pages:
            title = r["pageTitle"] if r["pageTitle"] != "(not set)" else r["pagePath"]
            lines.append(f"• `{r['pagePath']}` — {title}: {int(r['screenPageViews']):,} views")

    if top_countries:
        lines += ["", "*Top Countries*"]
        for r in top_countries:
            lines.append(f"• {r['country']}: {int(r['sessions']):,} sessions ({int(r['totalUsers']):,} users)")

    return "\n".join(lines)


# ── Slack sender ──────────────────────────────────────────────────────────────

def send_to_slack(message, cfg):
    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {cfg.SLACK_BOT_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"channel": cfg.SLACK_CHANNEL_ID, "text": message, "mrkdwn": True},
    )
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack error: {data.get('error')}")
    print("  Slack message sent!")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Zingg GA4 daily report → Slack")
    parser.add_argument("--config",    required=True, help="Path to config.py")
    parser.add_argument("--date",      default="yesterday",
                        help="Date to report on: 'yesterday' (default), 'today', or YYYY-MM-DD")
    parser.add_argument("--days",      type=int, default=1,
                        help="Number of days to aggregate (default: 1 = yesterday only)")
    args = parser.parse_args()

    cfg = load_config(args.config)

    # Resolve date range
    if args.date == "yesterday":
        end   = datetime.now(timezone.utc) - timedelta(days=1)
        start = end - timedelta(days=args.days - 1)
        date_label = end.strftime("%b %d, %Y") if args.days == 1 else \
                     f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
        date_range = (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    elif args.date == "today":
        today = datetime.now(timezone.utc)
        date_label = today.strftime("%b %d, %Y") + " (so far)"
        date_range = (today.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
    else:
        date_range = (args.date, args.date)
        date_label = args.date

    print(f"Fetching GA4 data for {date_label}...")
    client      = get_ga_client(cfg)
    property_id = cfg.GA_PROPERTY_ID

    overview      = fetch_overview(client, property_id, date_range)
    top_pages     = fetch_top_pages(client, property_id, date_range)
    top_sources   = fetch_top_sources(client, property_id, date_range)
    top_countries = fetch_top_countries(client, property_id, date_range)
    devices       = fetch_devices(client, property_id, date_range)

    print("Sending to Slack...")
    message = build_message(overview, top_pages, top_sources, top_countries, devices, date_label, cfg)
    print(message)
    print()
    send_to_slack(message, cfg)

    print("Done.")


if __name__ == "__main__":
    main()
