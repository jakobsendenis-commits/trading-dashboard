#!/bin/bash

mkdir -p ~/Desktop/bot/logs
cd ~/Desktop/bot

echo "🚀 Starting all bots..."

python3 eth_bot.py > logs/eth.log 2>&1 &
python3 ada_lorentzian_bot.py > logs/ada.log 2>&1 &
python3 avax_lorentzian_bot.py > logs/avax.log 2>&1 &
python3 aero_lorentzian_bot.py > logs/aero.log 2>&1 &
python3 tia_ma_bot.py > logs/tia.log 2>&1 &
python3 jasmy_lorentzian_bot.py > logs/jasmy.log 2>&1 &
python3 popcat_lorentzian_bot.py > logs/popcat.log 2>&1 &

sleep 2
echo "✅ All bots started"

echo "🔄 Starting GitHub auto-updater..."
while true; do
    sleep 300
    
    cd ~/Desktop/bot
    if git diff --quiet all_trades.csv 2>/dev/null; then
        echo "$(date): No changes"
    else
        git add all_trades.csv
        git commit -m "Auto-update $(date '+%Y-%m-%d %H:%M')"
        git push
        echo "$(date): ✅ GitHub updated"
    fi
done
