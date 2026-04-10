#!/usr/bin/env python3
"""
Zingg GitHub Stats — daily collector + Slack notifier

Usage:
  python zingg_daily_stats.py --config /path/to/config.py

Cron (9am daily):
  0 9 * * * /path/to/venv/bin/python /path/to/zingg_daily_stats.py --config /path/to/config.py >> /path/to/stats.log 2>&1
"""

import argparse
import importlib.util
import requests
import csv
import io
import base64
from datetime import datetime, timezone


def load_config(config_path):
    """Load config.py from any absolute or relative path."""
    spec = importlib.util.spec_from_file_location("config", config_path)
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    return cfg


# ── GitHub source repo (read traffic) ────────────────────────────────────────

def gh_get(path, cfg):
    url = f"https://api.github.com/repos/{cfg.SOURCE_REPO}/{path}".rstrip("/")
    r = requests.get(url, headers={
        "Authorization": f"token {cfg.GITHUB_PAT_SOURCE}",
        "Accept": "application/vnd.github+json",
    })
    r.raise_for_status()
    return r.json()


# ── GitHub storage repo (read/write CSVs) ────────────────────────────────────

def csv_filename(prefix):
    """e.g. views_2026_04.csv — rotates every month"""
    now = datetime.now(timezone.utc)
    return f"{prefix}_{now.year}_{now.month:02d}.csv"


def fetch_csv_from_github(filename, cfg):
    """Returns (content_str, sha) or ("", None) if file doesn't exist yet."""
    url = f"https://api.github.com/repos/{cfg.TRAFFIC_REPO}/contents/{filename}"
    r = requests.get(url, headers={
        "Authorization": f"token {cfg.GITHUB_PAT_STORAGE}",
        "Accept": "application/vnd.github+json",
    })
    if r.status_code == 404:
        return "", None
    r.raise_for_status()
    data = r.json()
    return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]


def push_csv_to_github(filename, content_str, sha, commit_msg, cfg):
    """Create or update a CSV file in the storage repo."""
    url = f"https://api.github.com/repos/{cfg.TRAFFIC_REPO}/contents/{filename}"
    payload = {
        "message": commit_msg,
        "content": base64.b64encode(content_str.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers={
        "Authorization": f"token {cfg.GITHUB_PAT_STORAGE}",
        "Accept": "application/vnd.github+json",
    }, json=payload)
    r.raise_for_status()


def load_existing_keys(content_str, key_columns):
    keys = set()
    if not content_str.strip():
        return keys
    for row in csv.DictReader(io.StringIO(content_str)):
        keys.add(tuple(row[c] for c in key_columns))
    return keys


def append_rows(content_str, fieldnames, new_rows, key_columns):
    """Append only rows not already present. Returns (updated_str, added_count)."""
    existing_keys = load_existing_keys(content_str, key_columns)

    if not content_str.strip():
        out = io.StringIO()
        csv.DictWriter(out, fieldnames=fieldnames, lineterminator="\n").writeheader()
        body = out.getvalue()
    else:
        body = content_str.rstrip("\n") + "\n"

    added = 0
    for row in new_rows:
        key = tuple(str(row[c]) for c in key_columns)
        if key not in existing_keys:
            out = io.StringIO()
            csv.DictWriter(out, fieldnames=fieldnames, lineterminator="\n").writerow(row)
            body += out.getvalue()
            existing_keys.add(key)
            added += 1

    return body, added


# ── Per-dataset updaters ──────────────────────────────────────────────────────

def update_views(views, cfg):
    filename   = csv_filename("views")
    fieldnames = ["date", "views", "unique_visitors"]
    rows = [
        {"date": v["timestamp"][:10], "views": v["count"], "unique_visitors": v["uniques"]}
        for v in views.get("views", [])
    ]
    content, sha = fetch_csv_from_github(filename, cfg)
    updated, added = append_rows(content, fieldnames, rows, key_columns=["date"])
    if added:
        push_csv_to_github(filename, updated, sha, f"Add {added} view row(s)", cfg)
    print(f"  views:      {added} new rows → {filename}")


def update_clones(clones, cfg):
    filename   = csv_filename("clones")
    fieldnames = ["date", "clones", "unique_cloners"]
    rows = [
        {"date": c["timestamp"][:10], "clones": c["count"], "unique_cloners": c["uniques"]}
        for c in clones.get("clones", [])
    ]
    content, sha = fetch_csv_from_github(filename, cfg)
    updated, added = append_rows(content, fieldnames, rows, key_columns=["date"])
    if added:
        push_csv_to_github(filename, updated, sha, f"Add {added} clone row(s)", cfg)
    print(f"  clones:     {added} new rows → {filename}")


def update_referrers(referrers, cfg):
    filename   = csv_filename("referrers")
    fieldnames = ["fetched_date", "referrer", "views", "unique_visitors"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = [
        {"fetched_date": today, "referrer": r["referrer"],
         "views": r["count"], "unique_visitors": r["uniques"]}
        for r in (referrers or [])
    ]
    content, sha = fetch_csv_from_github(filename, cfg)
    updated, added = append_rows(content, fieldnames, rows, key_columns=["fetched_date", "referrer"])
    if added:
        push_csv_to_github(filename, updated, sha, f"Add {added} referrer row(s)", cfg)
    print(f"  referrers:  {added} new rows → {filename}")


def update_paths(paths, cfg):
    filename   = csv_filename("paths")
    fieldnames = ["fetched_date", "path", "views", "unique_visitors"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = [
        {"fetched_date": today, "path": p["path"],
         "views": p["count"], "unique_visitors": p["uniques"]}
        for p in (paths or [])
    ]
    content, sha = fetch_csv_from_github(filename, cfg)
    updated, added = append_rows(content, fieldnames, rows, key_columns=["fetched_date", "path"])
    if added:
        push_csv_to_github(filename, updated, sha, f"Add {added} path row(s)", cfg)
    print(f"  paths:      {added} new rows → {filename}")


def update_repo_stats(info, cfg):
    filename   = csv_filename("repo_stats")
    fieldnames = ["date", "stars", "forks", "watchers", "open_issues"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = [{
        "date":        today,
        "stars":       info["stargazers_count"],
        "forks":       info["forks_count"],
        "watchers":    info["subscribers_count"],
        "open_issues": info["open_issues_count"],
    }]
    content, sha = fetch_csv_from_github(filename, cfg)
    updated, added = append_rows(content, fieldnames, rows, key_columns=["date"])
    if added:
        push_csv_to_github(filename, updated, sha, f"Add repo stats for {today}", cfg)
    print(f"  repo_stats: {added} new rows → {filename}")


# ── Slack ─────────────────────────────────────────────────────────────────────

def build_slack_message(info, views, clones, referrers, paths, cfg):
    today = datetime.now(timezone.utc).strftime("%b %d, %Y")
    month = datetime.now(timezone.utc).strftime("%Y_%m")
    base  = f"https://github.com/{cfg.TRAFFIC_REPO}/blob/main"

    lines = [
        f"*Zingg GitHub Stats — {today}*",
        f"_<https://github.com/{cfg.SOURCE_REPO}|zingg-ai/zingg>_",
        "",
        "*Repository Overview*",
        f"• Stars: *{info['stargazers_count']:,}*",
        f"• Forks: *{info['forks_count']:,}*",
        f"• Watchers: *{info['subscribers_count']:,}*",
        f"• Open Issues: *{info['open_issues_count']:,}*",
        "",
        "*Traffic — Last 14 Days*",
        f"• Page Views: *{views['count']:,}* ({views['uniques']:,} unique)",
        f"• Git Clones: *{clones['count']:,}* ({clones['uniques']:,} unique)",
    ]

    if referrers:
        lines += ["", "*Top Referrers*"]
        for ref in referrers:
            lines.append(f"• {ref['referrer']}: {ref['count']:,} views ({ref['uniques']:,} unique)")

    if paths:
        lines += ["", "*Top Paths*"]
        for p in paths:
            lines.append(f"• `{p['path']}`: {p['count']:,} views ({p['uniques']:,} unique)")

    lines += [
        "",
        f"*CSV Archive ({month})*",
        f"<{base}/views_{month}.csv|views> · "
        f"<{base}/clones_{month}.csv|clones> · "
        f"<{base}/referrers_{month}.csv|referrers> · "
        f"<{base}/paths_{month}.csv|paths> · "
        f"<{base}/repo_stats_{month}.csv|repo stats>",
    ]

    return "\n".join(lines)


def send_to_slack(message, cfg):
    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {cfg.SLACK_BOT_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"channel": cfg.SLACK_CHANNEL_ID, "text": message, "mrkdwn": True}
    )
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack error: {data.get('error')}")
    print("  Slack message sent!")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Zingg daily GitHub stats → Slack")
    parser.add_argument("--config", required=True, help="Path to config.py")
    args = parser.parse_args()

    cfg = load_config(args.config)

    print("Fetching GitHub traffic data...")
    info      = gh_get("", cfg)
    views     = gh_get("traffic/views", cfg)
    clones    = gh_get("traffic/clones", cfg)
    referrers = gh_get("traffic/popular/referrers", cfg)
    paths     = gh_get("traffic/popular/paths", cfg)

    print(f"Updating CSVs in {cfg.TRAFFIC_REPO}...")
    update_views(views, cfg)
    update_clones(clones, cfg)
    update_referrers(referrers, cfg)
    update_paths(paths, cfg)
    update_repo_stats(info, cfg)

    print("Sending Slack summary...")
    message = build_slack_message(info, views, clones, referrers, paths, cfg)
    send_to_slack(message, cfg)

    print("Done.")


if __name__ == "__main__":
    main()
