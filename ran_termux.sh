#!/data/data/com.termux/files/usr/bin/bash

# Termux launcher for the Telegram bot.
# Keep this script beside bot_complete.py and .env.
set -u

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
LOG_DIR="$APP_DIR/logs"
PYTHON_BIN="${PYTHON_BIN:-python}"
RESTART_DELAY="${RESTART_DELAY:-10}"

mkdir -p "$LOG_DIR"
cd "$APP_DIR" || exit 1

printf '%s\n' "[$(date -Is)] Termux bot launcher started" >> "$LOG_DIR/launcher.log"

while true; do
    printf '%s\n' "[$(date -Is)] Starting bot_complete.py" >> "$LOG_DIR/launcher.log"
    "$PYTHON_BIN" "$APP_DIR/bot_complete.py" >> "$LOG_DIR/bot.log" 2>&1
    EXIT_CODE=$?
    printf '%s\n' "[$(date -Is)] Bot stopped with exit code $EXIT_CODE; restarting in ${RESTART_DELAY}s" >> "$LOG_DIR/launcher.log"
    sleep "$RESTART_DELAY"
done