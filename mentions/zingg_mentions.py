#!/usr/bin/env python3
"""
Zingg Web Mentions Monitor — daily bot

Uses two sources:
  - Reddit API directly (fresh posts and comments, no auth needed)
  - Claude API with web search (blogs, HackerNews, LinkedIn, YouTube, general web)

Results are merged, deduplicated, and posted to Slack grouped by keyword.

Setup:
  pip install requests

  Add to config.py:
    ANTHROPIC_API_KEY = "sk-ant-..."

Usage:
  python zingg_mentions.py --config ~/.zingg/config.py
  python zingg_mentions.py --config ~/.zingg/config.py --keywords /path/to/keywords.txt
  python zingg_mentions.py --config ~/.zingg/config.py --mentions-config /path/to/mentions_config.txt

Cron (9am daily):
  0 9 * * * /path/to/venv/bin/python /path/to/zingg_mentions.py --config ~/.zingg/config.py >> ~/zingg-stats/stats.log 2>&1
"""

import argparse
import importlib.util
import json
import os
import time
import requests
from datetime import datetime, timedelta, timezone


# ── Config loader ─────────────────────────────────────────────────────────────

def load_config(config_path):
    spec = importlib.util.spec_from_file_location("config", config_path)
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    return cfg


# ── Mentions config parser ────────────────────────────────────────────────────

def parse_mentions_config(path):
    """
    Parse mentions_config.txt into sections:
      system_prompt, search_queries, exclude, keywords
    """
    sections = {
        "system_prompt": [],
        "search_queries": [],
        "exclude":        [],
        "keywords":       [],
    }
    current = None

    with open(path, "r") as f:
        for raw_line in f:
            line    = raw_line.rstrip("\n")
            stripped = line.strip()
            if stripped.startswith("#") or (stripped == "" and current is None):
                continue
            if stripped.startswith("[") and stripped.endswith("]"):
                current = stripped[1:-1].lower()
                continue
            if current and stripped and not stripped.startswith("#"):
                sections[current].append(stripped)

    return {
        "system_prompt":  "\n".join(sections["system_prompt"]).strip(),
        "search_queries": sections["search_queries"],
        "exclude":        [k.lower() for k in sections["exclude"]],
        "keywords":       sections["keywords"],
    }


def load_keywords_file(path):
    keywords = []
    with open(path, "r") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                keywords.append(stripped)
    return keywords


# ── Reddit API ────────────────────────────────────────────────────────────────

REDDIT_HEADERS = {"User-Agent": "zingg-mentions-bot/1.0 (by /u/zinggai)"}


def reddit_search(keyword, days=1, limit=25):
    """
    Search Reddit posts mentioning keyword from the last N days.
    Uses the public JSON API — no auth needed.
    Returns a list of mention dicts.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    results = []

    # Search posts
    try:
        r = requests.get(
            "https://www.reddit.com/search.json",
            params={"q": keyword, "sort": "new", "t": "week", "limit": limit},
            headers=REDDIT_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        posts = r.json().get("data", {}).get("children", [])

        for post in posts:
            d = post["data"]
            created = datetime.fromtimestamp(d["created_utc"], tz=timezone.utc)
            if created < cutoff:
                continue

            results.append({
                "keyword":   keyword,
                "title":     d.get("title", ""),
                "url":       f"https://reddit.com{d.get('permalink', '')}",
                "source":    "Reddit",
                "summary":   (d.get("selftext", "") or d.get("url", ""))[:200].strip() or None,
                "sentiment": "neutral",
                "date":      created.strftime("%Y-%m-%d"),
                "subreddit": d.get("subreddit_name_prefixed", ""),
                "score":     d.get("score", 0),
            })
    except Exception as e:
        print(f"  Reddit search error for '{keyword}': {e}")

    # Search comments
    try:
        r = requests.get(
            "https://www.reddit.com/search.json",
            params={"q": keyword, "sort": "new", "t": "week",
                    "limit": limit, "type": "comment"},
            headers=REDDIT_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        comments = r.json().get("data", {}).get("children", [])

        for comment in comments:
            d = comment["data"]
            created = datetime.fromtimestamp(d["created_utc"], tz=timezone.utc)
            if created < cutoff:
                continue

            results.append({
                "keyword":   keyword,
                "title":     f"Comment in r/{d.get('subreddit', '')}",
                "url":       f"https://reddit.com{d.get('permalink', '')}",
                "source":    "Reddit",
                "summary":   (d.get("body", "") or "")[:200].strip() or None,
                "sentiment": "neutral",
                "date":      created.strftime("%Y-%m-%d"),
                "subreddit": f"r/{d.get('subreddit', '')}",
                "score":     d.get("score", 0),
            })
    except Exception as e:
        print(f"  Reddit comments error for '{keyword}': {e}")

    return results


def filter_reddit_results(results, mcfg):
    """Apply exclude list to Reddit results."""
    filtered = []
    for m in results:
        text = f"{m['title']} {m.get('summary', '') or ''}".lower()
        if any(excl in text for excl in mcfg["exclude"]):
            continue
        filtered.append(m)
    return filtered


# ── Claude web search (non-Reddit) ───────────────────────────────────────────

# Search queries that explicitly skip Reddit (handled above)
CLAUDE_SKIP_PREFIXES = ("site:reddit.com",)


def fetch_web_mentions_for_keyword(keyword, mcfg, cfg):
    """
    Ask Claude to search the web (excluding Reddit) for a single keyword.
    Returns a list of mention dicts.
    """
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")

    # Build queries, skipping Reddit ones
    queries = "\n".join(
        f"- {q.replace('{keyword}', keyword)}"
        for q in mcfg["search_queries"]
        if not any(q.strip().startswith(p) for p in CLAUDE_SKIP_PREFIXES)
    )

    exclude_hint = ", ".join(mcfg["exclude"][:8]) if mcfg["exclude"] else "none"

    user_prompt = (
        f'Today is {today}. Search the web for recent mentions of "{keyword}" '
        f"from the last 24-48 hours. Skip Reddit — it is handled separately.\n\n"
        f"Use these search angles:\n{queries}\n\n"
        f"Exclude results clearly unrelated to the software — "
        f"for example: {exclude_hint}.\n\n"
        f"Return results as a JSON array. "
        f'Set "keyword" to "{keyword}" on every object.'
    )

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key":         cfg.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "anthropic-beta":    "web-search-2025-03-05",
            "content-type":      "application/json",
        },
        json={
            "model":      "claude-haiku-4-5-20251001",
            "max_tokens": 4096,
            "system":     mcfg["system_prompt"],
            "tools":      [{"type": "web_search_20250305", "name": "web_search"}],
            "messages":   [{"role": "user", "content": user_prompt}],
        },
    )

    if not response.ok:
        print(f"  Claude API error {response.status_code}: {response.text}")
    response.raise_for_status()
    data = response.json()

    text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")

    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    try:
        results = json.loads(text)
        for r in results:
            r.setdefault("keyword", keyword)
        return results
    except json.JSONDecodeError:
        print(f"  Warning: could not parse Claude response for '{keyword}':\n{text[:300]}")
        return []


# ── Combined fetcher ──────────────────────────────────────────────────────────

def fetch_all_mentions(keywords, mcfg, cfg):
    """
    For each keyword:
      1. Search Reddit directly
      2. Search the web via Claude (non-Reddit)
    Merge, deduplicate by URL, return combined list.
    """
    all_mentions = []
    seen_urls    = set()

    for keyword in keywords:
        print(f"  [{keyword}] searching Reddit...")
        reddit_results = reddit_search(keyword, days=1)
        reddit_results = filter_reddit_results(reddit_results, mcfg)
        print(f"    → {len(reddit_results)} Reddit result(s)")

        # Polite delay between Reddit calls
        time.sleep(1)

        print(f"  [{keyword}] searching web via Claude...")
        web_results = fetch_web_mentions_for_keyword(keyword, mcfg, cfg)
        print(f"    → {len(web_results)} web result(s)")

        for m in reddit_results + web_results:
            url = m.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_mentions.append(m)

    return all_mentions


# ── Slack message builder ─────────────────────────────────────────────────────

SENTIMENT_ICON = {
    "positive": ":large_green_circle:",
    "neutral":  ":white_circle:",
    "negative": ":red_circle:",
}
SOURCE_ICON = {
    "github":     ":computer:",
    "reddit":     ":speech_balloon:",
    "hackernews": ":orange_book:",
    "twitter":    ":bird:",
    "linkedin":   ":briefcase:",
    "youtube":    ":movie_camera:",
    "blog":       ":memo:",
    "medium":     ":memo:",
    "news":       ":newspaper:",
}


def build_slack_message(mentions, keywords, today):
    total    = len(mentions)
    positive = sum(1 for m in mentions if m.get("sentiment") == "positive")
    neutral  = sum(1 for m in mentions if m.get("sentiment") == "neutral")
    negative = sum(1 for m in mentions if m.get("sentiment") == "negative")

    lines = [
        f"*Web Mentions — {today}*",
        f"_keywords: {', '.join(keywords)} · "
        f"{total} mention{'s' if total != 1 else ''} · "
        f":large_green_circle: {positive}  "
        f":white_circle: {neutral}  "
        f":red_circle: {negative}_",
    ]

    if not mentions:
        lines.append("\nNo relevant mentions found today.")
        return "\n".join(lines)

    # Group by keyword → source
    by_keyword = {}
    for m in mentions:
        kw  = m.get("keyword", "unknown")
        src = m.get("source", "Other")
        by_keyword.setdefault(kw, {}).setdefault(src, []).append(m)

    for kw in keywords:
        if kw not in by_keyword:
            continue
        kw_total = sum(len(v) for v in by_keyword[kw].values())
        lines.append(f"\n*{kw}* — {kw_total} mention{'s' if kw_total != 1 else ''}")

        for source in sorted(by_keyword[kw].keys()):
            icon  = SOURCE_ICON.get(source.lower(), ":link:")
            items = by_keyword[kw][source]
            # Sort Reddit by score descending
            if source == "Reddit":
                items = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
            lines.append(f"{icon} *{source}* ({len(items)})")
            for m in items:
                sentiment = SENTIMENT_ICON.get(m.get("sentiment", "neutral"), ":white_circle:")
                date_str  = f"  _{m['date']}_" if m.get("date") else ""
                sub       = f" [{m['subreddit']}]" if m.get("subreddit") else ""
                score     = f" ↑{m['score']}" if m.get("score") else ""
                lines.append(f"  {sentiment} <{m['url']}|{m['title']}>{sub}{score}{date_str}")
                if m.get("summary"):
                    snippet = m["summary"][:140] + "..." if len(m["summary"]) > 140 else m["summary"]
                    lines.append(f"    _{snippet}_")

    return "\n".join(lines)


# ── Slack sender ──────────────────────────────────────────────────────────────

def send_to_slack(message, cfg):
    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {cfg.SLACK_BOT_TOKEN}",
            "Content-Type":  "application/json",
        },
        json={"channel": cfg.SLACK_CHANNEL_ID, "text": message, "mrkdwn": True},
    )
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack error: {data.get('error')}")
    print("  Slack message sent!")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Web mentions monitor")
    parser.add_argument("--config",          required=True,
                        help="Path to config.py")
    parser.add_argument("--mentions-config", default=None,
                        help="Path to mentions_config.txt (default: same dir as this script)")
    parser.add_argument("--keywords",        default=None,
                        help="Path to a plain text file with extra keywords, one per line")
    args = parser.parse_args()

    cfg = load_config(args.config)

    mentions_config_path = args.mentions_config or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "mentions_config.txt"
    )
    print(f"Loading mentions config from {mentions_config_path}")
    mcfg = parse_mentions_config(mentions_config_path)

    # Merge keywords from config + optional file
    keywords = list(mcfg["keywords"])
    if args.keywords:
        extra = load_keywords_file(args.keywords)
        print(f"  Loaded {len(extra)} extra keyword(s) from {args.keywords}")
        seen = set(k.lower() for k in keywords)
        for kw in extra:
            if kw.lower() not in seen:
                keywords.append(kw)
                seen.add(kw.lower())

    if not keywords:
        print("No keywords to search. Add them to mentions_config.txt or pass --keywords.")
        return

    today = datetime.now(timezone.utc).strftime("%b %d, %Y")
    print(f"Searching {len(keywords)} keyword(s) ({today}): {', '.join(keywords)}")

    mentions = fetch_all_mentions(keywords, mcfg, cfg)
    print(f"  {len(mentions)} total unique mention(s)")

    print("Sending to Slack...")
    message = build_slack_message(mentions, keywords, today)
    send_to_slack(message, cfg)

    print("Done.")


if __name__ == "__main__":
    main()
