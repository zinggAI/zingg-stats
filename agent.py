"""
Zingg AI - Reddit Opportunity Agent
Searches Reddit, scores relevance with Claude, and sends a daily
Slack digest with: post title, link, and suggested comment.

Secrets are loaded from ~/secrets/zingg_secrets.json
"""

import os
import csv
import json
import logging
import requests
import anthropic
from datetime import date
from pathlib import Path

from keywords import (
    ALL_BATCHES, BATCHES_PER_RUN, RESULTS_PER_KEYWORD,
    MAX_RESULTS_PER_RUN, MIN_RELEVANCE_SCORE, PRODUCT_CONTEXT,
    SEEN_POSTS_FILE, BATCH_STATE_FILE,
)

# ── Load secrets from ~/secrets/zingg_secrets.json ───────────────────────────
SECRETS_FILE = Path.home() / "secrets" / "zingg_secrets.json"

def load_secrets():
    if not SECRETS_FILE.exists():
        raise FileNotFoundError(
            f"Secrets file not found: {SECRETS_FILE}\n"
            f"Please create it with your API keys."
        )
    with open(SECRETS_FILE) as f:
        return json.load(f)

secrets = load_secrets()

ANTHROPIC_API_KEY = secrets["ANTHROPIC_API_KEY"]
GOOGLE_API_KEY    = secrets["GOOGLE_API_KEY"]
GOOGLE_CSE_ID     = secrets["GOOGLE_CSE_ID"]
SLACK_BOT_TOKEN   = secrets["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID  = secrets.get("SLACK_CHANNEL_ID", "C0ASH51VB9R")

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ── Batch rotation ────────────────────────────────────────────────────────────

def get_todays_batches():
    total = len(ALL_BATCHES)
    if os.path.exists(BATCH_STATE_FILE):
        with open(BATCH_STATE_FILE) as f:
            next_batch = int(f.read().strip())
    else:
        next_batch = 1
    todays = [((next_batch - 1 + i) % total) + 1 for i in range(BATCHES_PER_RUN)]
    next_start = ((next_batch - 1 + BATCHES_PER_RUN) % total) + 1
    with open(BATCH_STATE_FILE, "w") as f:
        f.write(str(next_start))
    log.info("Today's batches: %s | Next run starts at batch: %d", todays, next_start)
    return todays


# ── Deduplication ─────────────────────────────────────────────────────────────

def load_seen_urls():
    seen = set()
    if not os.path.exists(SEEN_POSTS_FILE):
        return seen
    with open(SEEN_POSTS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            seen.add(row["url"])
    log.info("Loaded %d previously seen URLs", len(seen))
    return seen


def save_seen_urls(results):
    file_exists = os.path.exists(SEEN_POSTS_FILE)
    with open(SEEN_POSTS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "title", "date_seen"])
        if not file_exists:
            writer.writeheader()
        for r in results:
            writer.writerow({
                "url": r["url"],
                "title": r["title"],
                "date_seen": date.today().isoformat(),
            })
    log.info("Saved %d URLs to %s", len(results), SEEN_POSTS_FILE)


# ── Search ────────────────────────────────────────────────────────────────────

def search_reddit(keyword, num):
    params = {
        "key": GOOGLE_API_KEY,
        "cx":  GOOGLE_CSE_ID,
        "q":   "site:reddit.com/r/ " + keyword,
        "num": min(num, 10),
    }
    posts = []
    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params=params, timeout=10
        )
        resp.raise_for_status()
        for item in resp.json().get("items", []):
            link = item.get("link", "")
            if "reddit.com/r/" in link and "/comments/" in link:
                base = link.split("?")[0].rstrip("/")
                subreddit = link.split("/r/")[1].split("/")[0] if "/r/" in link else ""
                posts.append({
                    "url": base, "subreddit": subreddit,
                    "title": item.get("title", "").replace(" - Reddit", "").strip(),
                    "snippet": item.get("snippet", ""),
                })
    except Exception as e:
        log.warning("Search failed for '%s': %s", keyword, e)
    return posts


# ── Fetch full Reddit post ────────────────────────────────────────────────────

REDDIT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ZinggAgent/1.0",
    "Accept": "application/json",
}

def fetch_reddit_post(post):
    json_url = post["url"].rstrip("/") + ".json?limit=10"
    try:
        resp = requests.get(json_url, headers=REDDIT_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        post_data     = data[0]["data"]["children"][0]["data"]
        comment_items = data[1]["data"]["children"]
        body = post_data.get("selftext", "").strip()
        if not body or body in ("[removed]", "[deleted]"):
            body = post.get("snippet", "")
        comments = []
        for item in comment_items:
            if item.get("kind") == "t1":
                c = item["data"].get("body", "").strip()
                if c and c not in ("[deleted]", "[removed]"):
                    comments.append(c)
        post["body"]     = body[:2000]
        post["comments"] = comments[:5]
        log.info("  Fetched full content: %s", post["title"][:50])
    except Exception as e:
        log.warning("  Could not fetch full content (using snippet): %s", e)
        post["body"]     = post.get("snippet", "")
        post["comments"] = []
    return post


# ── Claude analysis ───────────────────────────────────────────────────────────

def analyse_post(post):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    comments_text = "\n".join("- " + c for c in post.get("comments", [])) or "(no comments)"
    prompt = (
        "You are a developer advocate for Zingg AI.\n\n"
        "## About Zingg AI\n" + PRODUCT_CONTEXT + "\n\n"
        "## Reddit Post\n"
        "Subreddit : r/" + post["subreddit"] + "\n"
        "Title     : " + post["title"] + "\n"
        "Post Body : " + (post.get("body") or "(no body text)") + "\n\n"
        "Top Comments:\n" + comments_text + "\n\n"
        "## Task\n"
        "1. Score 1-10 for how relevant this post is for Zingg AI to engage.\n"
        "   Score 8-10: Someone asking about data dedup, entity resolution, record linkage at scale.\n"
        "   Score 5-7: Adjacent to Zingg domain but less directly actionable.\n"
        "   Score 1-4: Irrelevant (file backups, vinyl records, games, etc.)\n\n"
        "2. If score >= " + str(MIN_RELEVANCE_SCORE) + ", write a suggested comment that:\n"
        "   - Directly responds to what the person asked\n"
        "   - Is genuinely helpful, written as an experienced data engineer\n"
        "   - Is 2-4 sentences, natural Reddit tone\n"
        "   - Mentions Zingg AI ONLY if it fits completely naturally\n\n"
        'Respond ONLY with valid JSON: {"relevance_score": <int 1-10>, "suggested_comment": "<comment or empty string>"}'
    )
    try:
        response = client.messages.create(
            model="claude-haiku-4-5", max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        data    = json.loads(response.content[0].text.strip())
        score   = data.get("relevance_score", 0)
        comment = data.get("suggested_comment", "").strip()
        if score >= MIN_RELEVANCE_SCORE and comment:
            log.info("QUALIFIED Score %d/10: %s", score, post["title"][:60])
            return {**post, "relevance_score": score, "suggested_comment": comment}
        else:
            log.info("SKIPPED Score %d/10: %s", score, post["title"][:60])
    except Exception as e:
        log.warning("Claude failed for %s: %s", post["url"], e)
    return None


# ── Slack ─────────────────────────────────────────────────────────────────────

def send_to_slack(results, batches):
    today = date.today().strftime("%B %d, %Y")
    if not results:
        payload = {
            "channel": SLACK_CHANNEL_ID,
            "text": "Zingg AI Reddit Digest - " + today + "\nNo qualifying posts found today.",
        }
    else:
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn",
                "text": "*Zingg AI Reddit Digest - " + today + "*\n"
                        "Batches: " + str(batches) + "  |  Posts found: *" + str(len(results)) + "*"}},
            {"type": "divider"},
        ]
        for i, r in enumerate(results, 1):
            blocks.append({"type": "section", "text": {"type": "mrkdwn",
                "text": (
                    "*" + str(i) + ". " + r["title"] + "*\n"
                    "<" + r["url"] + "|View Post on Reddit>\n\n"
                    "*Suggested Comment:*\n" + r["suggested_comment"]
                )}})
            blocks.append({"type": "divider"})
        payload = {
            "channel": SLACK_CHANNEL_ID,
            "blocks": blocks,
            "text": "Zingg AI Reddit Digest - " + today,
        }
    try:
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            json=payload,
            headers={
                "Authorization": "Bearer " + SLACK_BOT_TOKEN,
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            log.info("Slack message sent - %d posts", len(results))
        else:
            log.error("Slack error: %s", data.get("error", "unknown"))
    except Exception as e:
        log.error("Slack send failed: %s", e)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_agent():
    log.info("=" * 60)
    log.info("Zingg AI Reddit Agent - Starting")
    log.info("=" * 60)
    batches   = get_todays_batches()
    seen_urls = load_seen_urls()
    results   = []
    searches  = 0
    for batch_num in batches:
        if len(results) >= MAX_RESULTS_PER_RUN:
            break
        log.info("-- Batch %d --", batch_num)
        for keyword in ALL_BATCHES[batch_num]:
            if len(results) >= MAX_RESULTS_PER_RUN:
                log.info("Reached %d results - stopping.", MAX_RESULTS_PER_RUN)
                break
            posts = search_reddit(keyword, RESULTS_PER_KEYWORD)
            searches += 1
            log.info("'%s' -> %d posts", keyword, len(posts))
            for post in posts:
                if len(results) >= MAX_RESULTS_PER_RUN:
                    break
                if post["url"] in seen_urls:
                    log.info("  Already seen: %s", post["title"][:50])
                    continue
                seen_urls.add(post["url"])
                post   = fetch_reddit_post(post)
                result = analyse_post(post)
                if result:
                    results.append(result)
    if results:
        save_seen_urls(results)
    send_to_slack(results, batches)
    log.info("=" * 60)
    log.info("Done | Posts: %d | Searches used: %d/100", len(results), searches)
    log.info("=" * 60)


if __name__ == "__main__":
    run_agent()
