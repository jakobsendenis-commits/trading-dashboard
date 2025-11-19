#!/bin/bash

# GITHUB AUTO-SYNC - Opdaterer dashboard hver 5. minut

echo "🔄 GitHub Auto-Sync starter..."

# Setup git repo hvis det ikke findes
if [ ! -d "$HOME/Desktop/trading-dashboard/.git" ]; then
    echo "📁 Opretter git repo..."
    mkdir -p "$HOME/Desktop/trading-dashboard"
    cd "$HOME/Desktop/trading-dashboard"
    git init
    git remote add origin https://github.com/jakobsendenis-commits/trading-dashboard.git
    git config pull.rebase false
    
    # Pull existing files
    git pull origin main 2>/dev/null || echo "Nyt repo"
fi

cd "$HOME/Desktop/trading-dashboard"

# Loop forever
while true; do
    # Copy latest CSV
    if [ -f "$HOME/Desktop/all_trades.csv" ]; then
        cp "$HOME/Desktop/all_trades.csv" .
        
        # Check if there are changes
        if ! git diff --quiet all_trades.csv 2>/dev/null; then
            echo "[$(date '+%H:%M:%S')] 📤 Opdaterer dashboard..."
            git add all_trades.csv
            git commit -m "Auto-update: $(date '+%Y-%m-%d %H:%M:%S')"
            git push origin main 2>&1 | grep -v "Username\|Password"
            echo "[$(date '+%H:%M:%S')] ✅ Dashboard opdateret!"
        else
            echo "[$(date '+%H:%M:%S')] ⏭️  Ingen ændringer"
        fi
    else
        echo "[$(date '+%H:%M:%S')] ⚠️  Venter på all_trades.csv..."
    fi
    
    # Vent 5 minutter
    sleep 300
done
