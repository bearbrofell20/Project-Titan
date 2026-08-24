# Running Project Titan 24/7 on your own machine

This session's container pauses whenever the chat goes idle, so the bot can't
finish its 7-day testing week here. To run it truly always-on, put it on a
machine that stays awake — a spare laptop that never sleeps, a Raspberry Pi, or
a cheap always-on cloud VM (a $5–6/mo DigitalOcean/Linode/Hetzner box is plenty;
the bot uses almost no CPU or memory).

You need two things: your **OANDA practice API token** and your **account ID**
(`101-001-39975042-001`). Get/regenerate the token at
`OANDA → Manage API Access` on your practice account.

---

## Option A — one command (recommended)

On any Linux/Mac box with `bash`. This installs Docker if missing, asks for your
token, writes a git-ignored `.env`, and launches the bot so it restarts on crash
**and on reboot**.

```bash
git clone https://github.com/bearbrofell20/project-titan.git
cd project-titan
git checkout claude/coded-auto-trader-f730za
bash deploy/setup.sh
```

It prints your dashboard URL at the end (e.g. `http://<your-ip>:8080`).

Manage it:

```bash
docker compose logs -f      # watch it trade live
docker compose down         # stop it
docker compose up -d        # start it again
```

---

## Option B — Docker by hand

```bash
git clone https://github.com/bearbrofell20/project-titan.git
cd project-titan && git checkout claude/coded-auto-trader-f730za

cat > .env <<'EOF'
OANDA_API_TOKEN=PASTE_YOUR_PRACTICE_TOKEN_HERE
OANDA_ACCOUNT_ID=101-001-39975042-001
OANDA_API_URL=https://api-fxpractice.oanda.com
OANDA_DRY_RUN=false
EOF
chmod 600 .env

docker compose up -d --build
```

The winning config (ema_trend 20/60 on the JPY crosses AUD_JPY + EUR_JPY, H1,
signals-only, +$50 probation bar) is baked into `docker-compose.yml` as defaults
— you only need the two credentials above. These two pairs are the only ones with
a validated positive edge (see AUDIT.md). Open `http://localhost:8080` (or the
machine's IP) for the dashboard.

---

## Option C — no Docker (systemd on a Linux VPS)

```bash
git clone https://github.com/bearbrofell20/project-titan.git /opt/project-titan
cd /opt/project-titan && git checkout claude/coded-auto-trader-f730za
pip3 install requests

sudo cp deploy/titan.service /etc/systemd/system/titan.service
sudo mkdir -p /etc/titan
sudo tee /etc/titan/titan.env >/dev/null <<'EOF'
OANDA_API_TOKEN=PASTE_YOUR_PRACTICE_TOKEN_HERE
OANDA_ACCOUNT_ID=101-001-39975042-001
OANDA_API_URL=https://api-fxpractice.oanda.com
OANDA_DRY_RUN=false
OANDA_STRATEGY=breakout
OANDA_INSTRUMENTS=XAU_USD
OANDA_TIMEFRAME=H1
OANDA_CANDLE_COUNT=120
OANDA_BREAKOUT_LOOKBACK=40
OANDA_TREND_FILTER=false
OANDA_STOP_LOSS_PIPS=200
OANDA_TAKE_PROFIT_PIPS=400
OANDA_RISK_PER_TRADE=100
OANDA_MIN_OPEN_TRADES=0
OANDA_TRIAL_MIN_PNL=50
EOF
sudo chmod 600 /etc/titan/titan.env

sudo systemctl daemon-reload
sudo systemctl enable --now titan
journalctl -u titan -f       # follow the live log
```

Edit `titan.service`'s `User=` / `WorkingDirectory=` if your paths differ.

---

## Watching it

- **Dashboard** — `http://<machine-ip>:8080`: the JARVIS globe, live signals,
  open trades, and the Testing Week scorecard, refreshing on its own.
- **Trial state** persists in `trade_logs/probation.json`. If the strategy
  fails the week it writes `PURGATORY.txt` and stops trading until you delete
  that file by hand.

## Notes / safety

- This is your **practice** account (`api-fxpractice`). Live trading would need
  `OANDA_API_URL=https://api-fxtrade.oanda.com` **and** `OANDA_ALLOW_LIVE=true`
  — don't set those unless you truly mean real money.
- `.env` / `titan.env` hold your token — they're git-ignored and `chmod 600`.
  Regenerate the OANDA token if it was ever pasted into a chat.
- Only expose port 8080 to yourself (LAN or a VPN/SSH tunnel). The dashboard's
  Start/Stop controls are localhost-only, but don't put the page on the open
  internet without a password in front of it.
