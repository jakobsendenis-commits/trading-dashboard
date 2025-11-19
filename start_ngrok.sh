#!/bin/bash

osascript <<APPLESCRIPT
tell application "Terminal"
    do script "ngrok http 5002"
    do script "ngrok http 5005"
    do script "ngrok http 5003"
    do script "ngrok http 5004"
    do script "ngrok http 5006"
    do script "ngrok http 5008"
    do script "ngrok http 5007"
end tell
APPLESCRIPT
