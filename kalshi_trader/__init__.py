"""Project Titan — a coded auto trader for the Kalshi event-contracts exchange.

The package is organised into small, testable pieces:

- :mod:`kalshi_trader.config`      — environment / credential configuration
- :mod:`kalshi_trader.models`      — typed data structures (markets, orders, ...)
- :mod:`kalshi_trader.client`      — authenticated REST client for the Kalshi API
- :mod:`kalshi_trader.risk`        — risk limits that gate every order
- :mod:`kalshi_trader.strategies`  — pluggable trading strategies
- :mod:`kalshi_trader.engine`      — the trading loop tying everything together
- :mod:`kalshi_trader.cli`         — command line entry point

By design the engine runs in **dry-run** mode unless it is explicitly told to
trade live, so importing and experimenting with this package never risks real
money.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
