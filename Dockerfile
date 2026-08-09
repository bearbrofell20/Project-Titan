# Minimal image to run the OANDA bot + dashboard 24/7.
FROM python:3.11-slim

WORKDIR /app

# The OANDA bot + dashboard need only `requests` (dashboard is pure stdlib).
RUN pip install --no-cache-dir requests

COPY oanda_trader.py probation.py dashboard.py run_all.py kalshi_bot.py ./
COPY news.py news_bot.py ./
COPY kalshi_trader/ ./kalshi_trader/

# Dashboard port
EXPOSE 8080

# Credentials come from the environment (OANDA_API_TOKEN, OANDA_ACCOUNT_ID, …),
# never baked into the image. Trade logs persist via a mounted volume.
ENV OANDA_LOG_DIR=/data/trade_logs
VOLUME ["/data"]

CMD ["python", "run_all.py"]
