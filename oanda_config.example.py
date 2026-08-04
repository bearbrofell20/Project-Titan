"""OANDA credentials / overrides for oanda_trader.py.

Copy this file to `oanda_config.py` (which is git-ignored) and fill in your
token, OR skip the file entirely and export environment variables instead:

    export OANDA_API_TOKEN='your-practice-token'
    export OANDA_ACCOUNT_ID='101-001-XXXXXXX-001'

Environment variables and this file can be mixed; the bot reads the token from
API_TOKEN here first, then falls back to $OANDA_API_TOKEN.
"""

# --- Required --------------------------------------------------------------
API_TOKEN = ""  # your OANDA v20 API token (practice token for demo)

# --- Optional overrides ----------------------------------------------------
# These mirror environment variables; setting the env var has the same effect.
# ACCOUNT_ID via OANDA_ACCOUNT_ID
# API_URL    via OANDA_API_URL   (demo: https://api-fxpractice.oanda.com)
# DRY_RUN    via OANDA_DRY_RUN=true   -> log intended orders, send nothing
# ALLOW_LIVE via OANDA_ALLOW_LIVE=yes -> required to use the real-money endpoint


def validate_config():
    """Optional hook. The bot also runs its own validation at startup."""
    problems = []
    if not API_TOKEN:
        problems.append("API_TOKEN is empty (or export OANDA_API_TOKEN instead)")
    return problems
