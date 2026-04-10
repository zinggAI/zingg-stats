#!/bin/bash
cd ~/zingg-stats
source venv/bin/activate

echo "$(date '+%H:%M:%S') Sending Github Stats report..." >> $LOG
python zingg_daily_stats.py >> ~/zingg-stats/stats.log 2>&1

echo "$(date '+%H:%M:%S') Visualising Github Stats report..." >> $LOG
python visualise.py >> ~/zingg-stats/stats.log 2>&1

echo "$(date '+%H:%M:%S') Sending GA report..." >> $LOG
python ga_daily_report.py --config ~/secrets/config_ga.py  >> ~/zingg-stats/stats.log 2>&1
deactivate
