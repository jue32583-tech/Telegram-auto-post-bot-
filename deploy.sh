#!/bin/bash
set -euo pipefail

# Telegram Auto Post Bot deployment helper.
# Secrets must be provided through .env or the hosting platform's environment variables.

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install it with: sudo apt install python3 python3-pip"
  exit 1
fi

if [ ! -f .env ]; then
  echo "Missing .env. Copy .env.example to .env and fill it with private values."
  exit 1
fi

python3 -m pip install -r requirements.txt
mkdir -p logs

if [ "${1:-start}" = "restart" ] && [ -f bot.pid ]; then
  kill "$(cat bot.pid)" 2>/dev/null || true
  rm -f bot.pid
  sleep 2
fi

if [ "${1:-start}" = "stop" ]; then
  if [ -f bot.pid ]; then
    kill "$(cat bot.pid)" 2>/dev/null || true
    rm -f bot.pid
  fi
  echo "Bot stopped."
  exit 0
fi

if [ -f bot.pid ] && kill -0 "$(cat bot.pid)" 2>/dev/null; then
  echo "Bot is already running with PID $(cat bot.pid)."
  exit 0
fi

nohup python3 bot.py > logs/bot.log 2>&1 &
echo $! > bot.pid
echo "Bot started with PID $(cat bot.pid)."
echo "View logs: tail -f logs/bot.log"
