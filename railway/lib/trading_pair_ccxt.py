"""
bots.trading_pair: Bybit-style ticker (e.g. BTCUSDT, BTCUSDT.P) or legacy CCXT BASE/QUOTE.
Hub + worker use same DB string for Redis market_data:{trading_pair}; CCXT calls use mapped symbol.
"""
from __future__ import annotations

import re
from typing import Tuple

# Bybit / TradingView perp suffix; linear USDT perp when combined with USDT tail.
_BYBIT_TICKER_RE = re.compile(r"^[A-Z0-9]{3,}\.P$|^[A-Z0-9]{5,}$")
_LEGACY_SLASH_RE = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+(:[A-Z0-9]+)?$")


def normalize_trading_pair(raw: str) -> str:
    return (raw or "").strip().upper()


def is_valid_trading_pair(s: str) -> bool:
    t = normalize_trading_pair(s)
    if not t:
        return False
    if "/" in t:
        return bool(_LEGACY_SLASH_RE.match(t))
    return bool(_BYBIT_TICKER_RE.match(t))


def trading_pair_to_ccxt(trading_pair: str, market_type: str = "linear") -> str | None:
    """
    Linear USDT perp → BASE/USDT:USDT; spot USDT → BASE/USDT; inverse → BASE/USD:BASE.
    Legacy ``BTC/USDT`` or ``BTC/USDT:USDT`` returned unchanged (uppercased).
    """
    s = normalize_trading_pair(trading_pair)
    if not s:
        return None
    if "/" in s:
        return s
    mt = (market_type or "linear").lower()
    perp_suffix = s.endswith(".P")
    sym = s[:-2] if perp_suffix else s
    for quote in ("USDT", "USDC", "USD"):
        if sym.endswith(quote):
            base = sym[: -len(quote)]
            if len(base) < 1:
                return None
            if quote == "USD" and mt == "inverse":
                return f"{base}/{quote}:{base}"
            if quote in ("USDT", "USDC"):
                if perp_suffix or mt == "linear":
                    return f"{base}/{quote}:{quote}"
                return f"{base}/{quote}"
            return None
    return None


def base_quote_for_balance(trading_pair: str, market_type: str = "linear") -> Tuple[str, str]:
    """(base, quote) for free-balance checks; quote is settlement asset."""
    s = normalize_trading_pair(trading_pair)
    if "/" in s:
        left, _, rest = s.partition("/")
        if ":" in rest:
            mid, _, settle = rest.partition(":")
            return left, settle or mid
        return left, rest
    mt = (market_type or "linear").lower()
    perp = s.endswith(".P")
    sym = s[:-2] if perp else s
    for quote in ("USDT", "USDC", "USD"):
        if sym.endswith(quote):
            base = sym[: -len(quote)]
            if quote == "USD" and mt == "inverse":
                return base, quote
            if quote in ("USDT", "USDC"):
                return base, quote
    return "", ""


def base_symbol_for_logs(trading_pair: str) -> str:
    b, _ = base_quote_for_balance(trading_pair, "linear")
    if b:
        return b
    s = normalize_trading_pair(trading_pair)
    if "/" in s:
        return s.split("/")[0]
    return s[:3] if s else "?"


def default_trading_pair() -> str:
    return "BTCUSDT.P"
