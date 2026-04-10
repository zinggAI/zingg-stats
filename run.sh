#!/bin/bash
cd ~/automations/zingg-stats
source venv/bin/activate
python zingg_daily_stats.py >> ~/automations/zingg-stats/stats.log 2>&1
deactivate
