#!/bin/bash

cd ~/Desktop/bot

# Check if all_trades.csv has changes
if git diff --quiet all_trades.csv 2>/dev/null; then
    echo "No changes to commit"
    exit 0
fi

# Commit and push
git add all_trades.csv
git commit -m "Update trades $(date '+%Y-%m-%d %H:%M')"
git push origin main 2>/dev/null || git push

echo "✅ GitHub updated at $(date)"
