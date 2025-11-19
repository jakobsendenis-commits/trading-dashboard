#!/bin/bash

# Start bots
osascript <<APPLESCRIPT1
tell application "Terminal"
    do script "cd ~/Desktop/bot && python3 eth_bot.py"
    do script "cd ~/Desktop/bot && python3 aero_lorentzian_bot.py"
    do script "cd ~/Desktop/bot && python3 ada_lorentzian_bot.py"
    do script "cd ~/Desktop/bot && python3 avax_lorentzian_bot.py"
    do script "cd ~/Desktop/bot && python3 tia_ma_bot.py"
    do script "cd ~/Desktop/bot && python3 jasmy_lorentzian_bot.py"
    do script "cd ~/Desktop/bot && python3 popcat_lorentzian_bot.py"
end tell
APPLESCRIPT1

sleep 5

# Start ngrok
osascript <<APPLESCRIPT2
tell application "Terminal"
    do script "ngrok http 5002"
    do script "ngrok http 5005"
    do script "ngrok http 5003"
    do script "ngrok http 5004"
    do script "ngrok http 5006"
    do script "ngrok http 5008"
    do script "ngrok http 5007"
end tell
APPLESCRIPT2
