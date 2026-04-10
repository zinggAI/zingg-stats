#!/bin/bash
cd ~/zingg-stats
source venv/bin/activate
python zingg_daily_stats.py >> ~/zingg-stats/stats.log 2>&1
python visualise.py >> ~/zingg-stats/stats.log 2>&1
deactivate
