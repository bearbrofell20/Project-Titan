#!/usr/bin/env bash
# Project Titan — one-shot 24/7 setup for a fresh Ubuntu/Debian server (or any
# Linux/Mac box with bash). Installs Docker if needed, writes a git-ignored .env,
# and launches the bot + dashboard so they restart on crash and on reboot.
#
#   git clone https://github.com/bearbrofell20/project-titan.git
#   cd project-titan
#   bash deploy/setup.sh
set -euo pipefail

echo "== Project Titan · 24/7 setup =="

# 1) Docker -----------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi

# 2) Credentials -> .env (git-ignored, chmod 600) ---------------------------
if [ ! -f .env ]; then
  read -rp "OANDA account ID [101-001-39975042-001]: " ACCT
  ACCT=${ACCT:-101-001-39975042-001}
  read -rsp "OANDA PRACTICE API token: " TOKEN; echo
  cat > .env <<EOF
OANDA_API_TOKEN=$TOKEN
OANDA_ACCOUNT_ID=$ACCT
OANDA_API_URL=https://api-fxpractice.oanda.com
# Backtest-winning config: ema_trend on tight majors, signals-only.
OANDA_STRATEGY=ema_trend
OANDA_INSTRUMENTS=EUR_USD,GBP_USD,USD_JPY,USD_CHF,AUD_USD,USD_CAD
OANDA_TREND_FILTER=true
OANDA_MIN_OPEN_TRADES=0
OANDA_RISK_PER_TRADE=10
OANDA_DRY_RUN=false
# Testing-week probation: must net +\$50 over 7 days to graduate.
OANDA_TRIAL_DAYS=7
OANDA_TRIAL_MIN_PNL=50
OANDA_TRIAL_MIN_TRADES=5
EOF
  chmod 600 .env
  echo "Wrote .env (permissions 600)."
else
  echo ".env already exists — leaving it as is."
fi

# 3) Launch (detached, auto-restart on crash + reboot) ----------------------
DOCKER="docker"; docker info >/dev/null 2>&1 || DOCKER="sudo docker"
$DOCKER compose up -d --build

IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo localhost)
echo
echo "Running 24/7."
echo "  Dashboard : http://${IP:-localhost}:8080"
echo "  Logs      : $DOCKER compose logs -f"
echo "  Stop      : $DOCKER compose down"
