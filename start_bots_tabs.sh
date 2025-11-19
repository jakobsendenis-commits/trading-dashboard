#!/bin/bash

osascript <<APPLESCRIPT
tell application "Terminal"
    do script "cd ~/Desktop/bot && python3 eth_bot.py"
    do script "cd ~/Desktop/bot && python3 aero_lorentzian_bot.py"
    do script "cd ~/Desktop/bot && python3 ada_lorentzian_bot.py"
    do script "cd ~/Desktop/bot && python3 avax_lorentzian_bot.py"
    do script "cd ~/Desktop/bot && python3 tia_ma_bot.py"
    do script "cd ~/Desktop/bot && python3 jasmy_lorentzian_bot.py"
    do script "cd ~/Desktop/bot && python3 popcat_lorentzian_bot.py"
end tell
APPLESCRIPT
