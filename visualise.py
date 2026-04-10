#!/usr/bin/env python3
"""
Zingg GitHub Stats — visualizer

Reads monthly CSV files from zinggAI/github_traffic, generates charts,
and uploads them to #repo-stats on Slack.

Usage:
  python visualize.py --config /path/to/config.py

  # specific month (defaults to current month)
  python visualize.py --config /path/to/config.py --month 2026-04

  # last N months automatically
  python visualize.py --config /path/to/config.py --last 3

  # multiple months manually
  python visualize.py --config /path/to/config.py --month 2026-02 --month 2026-03 --month 2026-04

pip install requests pandas matplotlib
"""

import argparse
import importlib.util
import io
import base64
import csv
import tempfile
import os
from datetime import datetime, timezone

import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")   # non-interactive backend, safe for cron
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


# ── Config loader ─────────────────────────────────────────────────────────────

def load_config(config_path):
    spec = importlib.util.spec_from_file_location("config", config_path)
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    return cfg


# ── GitHub CSV fetcher ────────────────────────────────────────────────────────

def fetch_csv(filename, cfg):
    """Fetch a CSV file from the traffic repo. Returns a DataFrame or None."""
    url = f"https://api.github.com/repos/{cfg.TRAFFIC_REPO}/contents/{filename}"
    r = requests.get(url, headers={
        "Authorization": f"token {cfg.GITHUB_PAT_STORAGE}",
        "Accept": "application/vnd.github+json",
    })
    if r.status_code == 404:
        print(f"  {filename} not found — skipping")
        return None
    r.raise_for_status()
    content = base64.b64decode(r.json()["content"]).decode("utf-8")
    return pd.read_csv(io.StringIO(content))


def load_months(prefix, months, cfg):
    """Load and concatenate CSV files for multiple months."""
    frames = []
    for month in months:
        year, mon = month.split("-")
        filename = f"{prefix}_{year}_{int(mon):02d}.csv"
        df = fetch_csv(filename, cfg)
        if df is not None:
            frames.append(df)
    if not frames:
        return None
    return pd.concat(frames).drop_duplicates().reset_index(drop=True)


# ── Chart generators ──────────────────────────────────────────────────────────

STYLE = {
    "views_color":        "#4C72B0",
    "unique_views_color": "#87AEDE",
    "clones_color":       "#DD8452",
    "unique_clones_color":"#F2BB96",
    "stars_color":        "#55A868",
    "forks_color":        "#C44E52",
    "grid_color":         "#E5E5E5",
    "bg":                 "#FAFAFA",
}


def style_ax(ax):
    ax.set_facecolor(STYLE["bg"])
    ax.grid(axis="y", color=STYLE["grid_color"], linewidth=0.8, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=9)


def save_fig(fig, name):
    """Save figure to a temp file and return the path."""
    path = os.path.join(tempfile.gettempdir(), f"zingg_{name}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def chart_views_clones(views_df, clones_df, months):
    """Dual-panel chart: daily views (top) and clones (bottom)."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    fig.suptitle(f"Zingg Traffic — {', '.join(months)}", fontsize=13, fontweight="bold", y=1.01)

    if views_df is not None and not views_df.empty:
        views_df["date"] = pd.to_datetime(views_df["date"])
        views_df = views_df.sort_values("date")
        ax1.bar(views_df["date"], views_df["views"],
                color=STYLE["views_color"], label="Views", zorder=3)
        ax1.bar(views_df["date"], views_df["unique_visitors"],
                color=STYLE["unique_views_color"], label="Unique visitors", zorder=3)
        ax1.set_ylabel("Page views", fontsize=9)
        ax1.legend(fontsize=8, framealpha=0)
        style_ax(ax1)

    if clones_df is not None and not clones_df.empty:
        clones_df["date"] = pd.to_datetime(clones_df["date"])
        clones_df = clones_df.sort_values("date")
        ax2.bar(clones_df["date"], clones_df["clones"],
                color=STYLE["clones_color"], label="Clones", zorder=3)
        ax2.bar(clones_df["date"], clones_df["unique_cloners"],
                color=STYLE["unique_clones_color"], label="Unique cloners", zorder=3)
        ax2.set_ylabel("Git clones", fontsize=9)
        ax2.legend(fontsize=8, framealpha=0)
        style_ax(ax2)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax2.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=30, ha="right")
    fig.tight_layout()
    return save_fig(fig, "views_clones")


def chart_repo_stats(stats_df, months):
    """Dual-axis line chart: stars (left axis) and forks (right axis) over time."""
    if stats_df is None or stats_df.empty:
        return None

    stats_df["date"] = pd.to_datetime(stats_df["date"])
    stats_df = stats_df.sort_values("date").drop_duplicates("date")

    fig, ax1 = plt.subplots(figsize=(10, 4))
    fig.suptitle(f"Zingg Stars & Forks — {', '.join(months)}", fontsize=13, fontweight="bold")

    ax1.plot(stats_df["date"], stats_df["stars"],
             color=STYLE["stars_color"], linewidth=2, marker="o", markersize=4, label="Stars")
    ax1.set_ylabel("Stars", fontsize=9, color=STYLE["stars_color"])
    ax1.tick_params(axis="y", labelcolor=STYLE["stars_color"])
    style_ax(ax1)

    ax2 = ax1.twinx()
    ax2.plot(stats_df["date"], stats_df["forks"],
             color=STYLE["forks_color"], linewidth=2, marker="s", markersize=4,
             linestyle="--", label="Forks")
    ax2.set_ylabel("Forks", fontsize=9, color=STYLE["forks_color"])
    ax2.tick_params(axis="y", labelcolor=STYLE["forks_color"])
    ax2.spines[["top"]].set_visible(False)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=8, framealpha=0)

    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=30, ha="right")
    fig.tight_layout()
    return save_fig(fig, "repo_stats")


def chart_referrers(referrers_df, months):
    """Horizontal bar chart of top referrers aggregated across selected months."""
    if referrers_df is None or referrers_df.empty:
        return None

    agg = (referrers_df.groupby("referrer")["views"]
           .sum().sort_values(ascending=True).tail(10))

    fig, ax = plt.subplots(figsize=(9, max(3, len(agg) * 0.5)))
    fig.suptitle(f"Top Referrers — {', '.join(months)}", fontsize=13, fontweight="bold")

    bars = ax.barh(agg.index, agg.values, color=STYLE["views_color"], zorder=3)
    ax.bar_label(bars, padding=4, fontsize=8)
    ax.set_xlabel("Total views", fontsize=9)
    style_ax(ax)
    fig.tight_layout()
    return save_fig(fig, "referrers")


def chart_paths(paths_df, months):
    """Horizontal bar chart of top paths aggregated across selected months."""
    if paths_df is None or paths_df.empty:
        return None

    agg = (paths_df.groupby("path")["views"]
           .sum().sort_values(ascending=True).tail(10))

    # Truncate long paths for readability
    agg.index = [p if len(p) <= 40 else "..." + p[-37:] for p in agg.index]

    fig, ax = plt.subplots(figsize=(9, max(3, len(agg) * 0.5)))
    fig.suptitle(f"Top Paths — {', '.join(months)}", fontsize=13, fontweight="bold")

    bars = ax.barh(agg.index, agg.values, color=STYLE["clones_color"], zorder=3)
    ax.bar_label(bars, padding=4, fontsize=8)
    ax.set_xlabel("Total views", fontsize=9)
    style_ax(ax)
    fig.tight_layout()
    return save_fig(fig, "paths")


# ── Slack uploader ────────────────────────────────────────────────────────────

def upload_image_to_slack(image_path, title, cfg):
    """Upload an image file to Slack and return the file permalink."""

    # Step 1: get upload URL
    filename = os.path.basename(image_path)
    size = os.path.getsize(image_path)

    r = requests.get(
        "https://slack.com/api/files.getUploadURLExternal",
        headers={"Authorization": f"Bearer {cfg.SLACK_BOT_TOKEN}"},
        params={"filename": filename, "length": size},
    )
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack getUploadURL error: {data.get('error')}")

    upload_url = data["upload_url"]
    file_id    = data["file_id"]

    # Step 2: upload the file
    with open(image_path, "rb") as f:
        r = requests.post(upload_url, files={"file": (filename, f, "image/png")})
    if r.status_code != 200:
        raise RuntimeError(f"Slack upload error: {r.text}")

    # Step 3: complete the upload and share to channel
    r = requests.post(
        "https://slack.com/api/files.completeUploadExternal",
        headers={
            "Authorization": f"Bearer {cfg.SLACK_BOT_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "files":           [{"id": file_id, "title": title}],
            "channel_id":      cfg.SLACK_CHANNEL_ID,
            "initial_comment": f"*{title}*",
        },
    )
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack completeUpload error: {data.get('error')}")

    print(f"  Uploaded: {title}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Zingg GitHub Stats — visualizer")
    parser.add_argument("--config", required=True, help="Path to config.py")
    parser.add_argument("--month", action="append", metavar="YYYY-MM",
                        help="Month(s) to visualize. Repeat for multiple: --month 2026-03 --month 2026-04")
    parser.add_argument("--last", type=int, metavar="N",
                        help="Visualize the last N months automatically, e.g. --last 3")
    args = parser.parse_args()

    cfg = load_config(args.config)

    # Resolve months — --last N takes priority, then --month, then default to current month
    if args.last:
        now = datetime.now(timezone.utc)
        months = []
        for i in range(args.last - 1, -1, -1):
            month_num = now.month - i
            year      = now.year + (month_num - 1) // 12
            month_num = ((month_num - 1) % 12) + 1
            months.append(f"{year}-{month_num:02d}")
    else:
        months = args.month or [datetime.now(timezone.utc).strftime("%Y-%m")]
    print(f"Generating charts for: {', '.join(months)}")

    print("Fetching CSVs from GitHub...")
    views_df     = load_months("views",      months, cfg)
    clones_df    = load_months("clones",     months, cfg)
    referrers_df = load_months("referrers",  months, cfg)
    paths_df     = load_months("paths",      months, cfg)
    stats_df     = load_months("repo_stats", months, cfg)

    print("Generating charts...")
    charts = [
        (chart_views_clones(views_df, clones_df, months), "Traffic: Views & Clones"),
        (chart_repo_stats(stats_df, months),               "Repository: Stars & Forks"),
        (chart_referrers(referrers_df, months),            "Top Referrers"),
        (chart_paths(paths_df, months),                    "Top Paths"),
    ]

    print("Uploading to Slack...")
    for path, title in charts:
        if path:
            upload_image_to_slack(path, title, cfg)
            os.unlink(path)   # clean up temp file

    print("Done.")


if __name__ == "__main__":
    main()
