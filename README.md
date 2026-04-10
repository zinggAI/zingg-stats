# Bunch of nifty automations for analytics

# Zingg GitHub Stats

Github provides repository analytics of only last 14 days. If you are an open source maintainer evangelising your software, this quickly becomes limiting. 
This repo is meant for those of us who would like to understand where people are discovering the repo, who is driving traffic, how the clones are gorowing etc.

Built with love by the [Zingg AI](https://www.zingg.ai) team, vibe coded through Claude.

The main script fetches daily traffic and repository stats from a given open source repository, appends them to CSV files organised by month, saves them in configurable repository and posts a summary to a Slack channel of your choice.

In the case of Zingg: 
open source repo [zinggAI/zingg](https://github.com/zinggAI/zingg)
stats repo [zinggAI/github_traffic](https://github.com/zinggAI/github_traffic), 
`#repo-stats` Slack channel

---

## Files

```
zingg_daily_stats.py   — main script
config.py              — credentials and settings (never commit this)
.gitignore             — excludes config.py and logs from git
README.md              — this file
```

---

## Setup

### 1. Clone or copy the scripts

```bash
mkdir ~/zingg-stats && cd ~/zingg-stats
# copy zingg_daily_stats.py and visualise.py here
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install requests
deactivate
```

### 3. Set up config.py

Copy `config.py` to a location of your choice (e.g. `~/.zingg/config.py`) and fill in all values:

```python
# GitHub PAT for reading traffic from zinggAI/zingg
# Needs: repo scope, must be a collaborator/admin on zinggAI/zingg
GITHUB_PAT_SOURCE  = "github_pat_..."

# GitHub PAT for writing CSVs to zinggAI/github_traffic
# Needs: contents:write scope on zinggAI/github_traffic
GITHUB_PAT_STORAGE = "github_pat_..."

# Repo to read traffic stats from
SOURCE_REPO  = "zinggAI/zingg"

# Repo to write CSV files to
TRAFFIC_REPO = "zinggAI/github_traffic"

# Slack bot token (xoxb-...) from api.slack.com/apps > OAuth & Permissions
# Needs: chat:write scope, bot must be invited to #repo-stats
SLACK_BOT_TOKEN  = "xoxb-..."
SLACK_CHANNEL_ID = "C0ARKLTMZL3"   # #repo-stats
```

### 4. Get a Slack bot token

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name it `Zingg Stats Bot`, select the zinggai workspace
3. Go to **OAuth & Permissions** → **Bot Token Scopes** → add `chat:write`
4. Click **Install to Workspace** → **Allow**
5. Copy the **Bot User OAuth Token** (`xoxb-...`) into `config.py`
6. In Slack, open `#repo-stats` and run `/invite @Zingg Stats Bot`

### 5. Test manually

```bash
source ~/zingg-stats/venv/bin/activate
python ~/zingg-stats/zingg_daily_stats.py --config ~/.zingg/config.py
```

---

## Running daily via cron

### Create a wrapper script

```bash
nano ~/zingg-stats/run.sh
```

```bash
#!/bin/bash
source ~/zingg-stats/venv/bin/activate
python ~/zingg-stats/zingg_daily_stats.py --config ~/.zingg/config.py >> ~/zingg-stats/stats.log 2>&1
deactivate
```

```bash
chmod +x ~/zingg-stats/run.sh
```

### Add to crontab

```bash
crontab -e
```

Add this line (runs every day at 9:00 AM):

```
0 9 * * * /Users/YOUR_USERNAME/zingg-stats/run.sh
```

> Use the full absolute path — cron does not expand `~/`. Run `echo $HOME` to find your home directory.

**macOS note:** cron may need Full Disk Access. Go to **System Settings → Privacy & Security → Full Disk Access** and add `/usr/sbin/cron`.

---

## CSV files

All CSV files are written to [zinggAI/github_traffic](https://github.com/zinggAI/github_traffic) and rotate monthly.

| File | Key column(s) | Description |
|---|---|---|
| `views_YYYY_MM.csv` | `date` | Daily page views and unique visitors |
| `clones_YYYY_MM.csv` | `date` | Daily git clones and unique cloners |
| `referrers_YYYY_MM.csv` | `fetched_date` + `referrer` | Top referring sites (GitHub max: 10) |
| `paths_YYYY_MM.csv` | `fetched_date` + `path` | Top visited paths (GitHub max: 10) |
| `repo_stats_YYYY_MM.csv` | `date` | Daily snapshot of stars, forks, watchers, open issues |

The script deduplicates on the key columns before appending, so running it multiple times in a day is safe — no duplicate rows will be written.

---
---

## Visualization

`visualize.py` reads the monthly CSV files from [zinggAI/github_traffic](https://github.com/zinggAI/github_traffic), generates charts, and uploads them to `#repo-stats` on Slack.

### Additional dependency

```bash
source ~/zingg-stats/venv/bin/activate
pip install pandas matplotlib
```

### Charts generated

| Chart | Description |
|---|---|
| **Traffic: Views & Clones** | Dual-panel bar chart — daily page views + unique visitors (top), git clones + unique cloners (bottom) |
| **Repository: Stars & Forks** | Dual-axis line chart — stars on left axis, forks on right axis |
| **Top Referrers** | Horizontal bar chart — total views per referrer aggregated across selected months |
| **Top Paths** | Horizontal bar chart — most visited paths aggregated across selected months |

### Usage

```bash
# current month only (default)
python visualize.py --config ~/.zingg/config.py

# last N months automatically
python visualize.py --config ~/.zingg/config.py --last 3

# specific months manually
python visualize.py --config ~/.zingg/config.py --month 2026-02 --month 2026-03 --month 2026-04
```

### Slack permissions

The Slack bot needs one additional scope to upload images. Go to [api.slack.com/apps](https://api.slack.com/apps) → your app → **OAuth & Permissions** → **Bot Token Scopes** → add `files:write`, then reinstall the app to the workspace.

### Running daily via cron

`run.sh` already calls both scripts in sequence — no changes needed. It runs `zingg_daily_stats.py` first to collect and store data, then `visualize.py --last 3` to generate and upload charts.

If you want to run the visualizer on a different schedule from the data collector (e.g. collect daily but chart weekly), you can split them into separate cron entries:

```
# collect stats every day at 9am
0 9 * * * /Users/YOUR_USERNAME/zingg-stats/venv/bin/python /Users/YOUR_USERNAME/zingg-stats/zingg_daily_stats.py --config ~/.zingg/config.py >> ~/zingg-stats/stats.log 2>&1

# generate charts every Monday at 9am
0 9 * * 1 /Users/YOUR_USERNAME/zingg-stats/venv/bin/python /Users/YOUR_USERNAME/zingg-stats/visualize.py --config ~/.zingg/config.py --last 3 >> ~/zingg-stats/stats.log 2>&1
```

## GitHub API limits

- **Traffic data** (views, clones, referrers, paths) requires the PAT owner to be a **collaborator or admin** on the source repo
- Views and clones history is available for the **last 14 days** only — this is a hard GitHub limit
- Referrers and paths are capped at **top 10** — this is a hard GitHub limit
- Running the script daily ensures no data is lost within the 14-day window

---

## Troubleshooting

**404 on GitHub API**
Make sure the PAT has access to `zinggAI/zingg` and the resource owner is set to the `zinggAI` org, not your personal account.

**Empty traffic data**
The PAT owner must be a collaborator or admin on `zinggAI/zingg`. Personal PATs scoped only to public repo metadata will not return traffic data.

**Slack `not_in_channel` error**
Run `/invite @Zingg Stats Bot` in `#repo-stats`.

**Cron not running**
Check `stats.log` for errors. Make sure the path in crontab is a full absolute path with no `~/` shorthand.

**`files:write` missing scope error**
Add `files:write` to your bot's OAuth scopes at [api.slack.com/apps](https://api.slack.com/apps) and reinstall the app.

**Charts show no data**
The CSV files for the requested months don't exist yet in `zinggAI/github_traffic`. Run `zingg_daily_stats.py` first to populate them.

**`ModuleNotFoundError: pandas` or `matplotlib`**
Run `pip install pandas matplotlib` inside the virtual environment.
