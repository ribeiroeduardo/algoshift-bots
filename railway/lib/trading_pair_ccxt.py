"""
Single instrument: Bitcoin USDT linear perpetual (Bybit / CCXT).

* DB ``bots.trading_pair`` and Redis ``market_data:{pair}`` use ``BTCUSDT``.
* CCXT / Bybit API use unified ``BTC/USDT:USDT``.
"""
from __future__ import annotations

from typing import Tuple

CANONICAL_PAIR = "BTCUSDT"
CCXT_BTC_USDT_LINEAR = "BTC/USDT:USDT"


def normalize_trading_pair(raw: str) -> str:
    """Uppercase strip; empty → canonical."""
    t = (raw or "").strip().upper()
    return t or CANONICAL_PAIR


def trading_pair_to_ccxt(_trading_pair: str, _market_type: str = "linear") -> str:
    """Always the BTC USDT linear perp unified symbol (arguments ignored)."""
    return CCXT_BTC_USDT_LINEAR


def display_pair_to_ccxt_or_raise(_display: str, _market_type: str = "linear") -> str:
    """Same as ``trading_pair_to_ccxt``; name kept for hub call sites."""
    return CCXT_BTC_USDT_LINEAR


def base_quote_for_balance(_trading_pair: str, _market_type: str = "linear") -> Tuple[str, str]:
    return "BTC", "USDT"


def base_symbol_for_logs(trading_pair: str) -> str:
    return "BTC"


def default_trading_pair() -> str:
    return CANONICAL_PAIR
