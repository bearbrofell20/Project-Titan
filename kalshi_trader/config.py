"""Configuration and credential loading for the Kalshi auto trader.

Configuration is sourced from environment variables (optionally loaded from a
``.env`` file) so that secrets never live in the repository.  See
``.env.example`` for the full list of supported variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Public REST endpoints for the two Kalshi environments.
ENDPOINTS = {
    "demo": "https://demo-api.kalshi.co/trade-api/v2",
    "prod": "https://api.elections.kalshi.com/trade-api/v2",
}


def _load_dotenv(path: str = ".env") -> None:
    """Minimal ``.env`` loader (no third-party dependency required).

    Lines of the form ``KEY=VALUE`` are read into ``os.environ`` unless the key
    is already set in the real environment (real env vars always win).
    """
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass
class Config:
    """Runtime configuration for the trader."""

    # --- Credentials -----------------------------------------------------
    api_key_id: Optional[str] = None
    private_key_path: Optional[str] = None

    # --- Environment -----------------------------------------------------
    environment: str = "demo"  # "demo" or "prod"

    # --- Safety ----------------------------------------------------------
    # When True the engine never submits real orders; it only logs what it
    # *would* do.  This is the default and must be turned off deliberately.
    dry_run: bool = True

    # --- Risk limits (see kalshi_trader.risk.RiskLimits) -----------------
    max_contracts_per_order: int = 10
    max_position_per_market: int = 50
    max_open_exposure_cents: int = 100_00  # $100.00 expressed in cents
    max_daily_loss_cents: int = 50_00      # $50.00 expressed in cents

    # Rule: never OPEN new positions when available cash is below this floor.
    min_cash_cents: int = 5_00             # $5.00
    # Rule: whenever a position can be closed for a profit, cash it out.
    cash_out_positive: bool = True

    # --- Engine ----------------------------------------------------------
    poll_interval_seconds: float = 30.0

    # --- Derived ---------------------------------------------------------
    base_url: str = field(init=False)

    def __post_init__(self) -> None:
        if self.environment not in ENDPOINTS:
            raise ValueError(
                f"Unknown environment {self.environment!r}; "
                f"expected one of {sorted(ENDPOINTS)}"
            )
        self.base_url = ENDPOINTS[self.environment]

    @classmethod
    def from_env(cls, dotenv_path: str = ".env") -> "Config":
        """Build a :class:`Config` from environment variables."""
        _load_dotenv(dotenv_path)

        def _int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            return int(raw) if raw not in (None, "") else default

        def _bool(name: str, default: bool) -> bool:
            raw = os.environ.get(name)
            if raw is None or raw == "":
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        return cls(
            api_key_id=os.environ.get("KALSHI_API_KEY_ID"),
            private_key_path=os.environ.get("KALSHI_PRIVATE_KEY_PATH"),
            environment=os.environ.get("KALSHI_ENV", "demo"),
            dry_run=_bool("KALSHI_DRY_RUN", True),
            max_contracts_per_order=_int("KALSHI_MAX_CONTRACTS_PER_ORDER", 10),
            max_position_per_market=_int("KALSHI_MAX_POSITION_PER_MARKET", 50),
            max_open_exposure_cents=_int("KALSHI_MAX_OPEN_EXPOSURE_CENTS", 100_00),
            max_daily_loss_cents=_int("KALSHI_MAX_DAILY_LOSS_CENTS", 50_00),
            min_cash_cents=_int("KALSHI_MIN_CASH_CENTS", 5_00),
            cash_out_positive=_bool("KALSHI_CASH_OUT_POSITIVE", True),
            poll_interval_seconds=float(os.environ.get("KALSHI_POLL_INTERVAL", "30")),
        )

    def require_credentials(self) -> None:
        """Raise a helpful error if credentials needed for live API calls are absent."""
        missing = []
        if not self.api_key_id:
            missing.append("KALSHI_API_KEY_ID")
        if not self.private_key_path:
            missing.append("KALSHI_PRIVATE_KEY_PATH")
        if missing:
            raise RuntimeError(
                "Missing credentials: "
                + ", ".join(missing)
                + ". Copy .env.example to .env and fill them in, or export them."
            )
