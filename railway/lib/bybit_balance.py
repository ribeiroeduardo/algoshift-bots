"""Sync Bybit balance for worker sizing (cached). Same env / modes as hub."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_MISSING = object()
_DISABLED = object()
_exchange: Any = _MISSING
_cache_quote: str | None = None
_cache_val: float | None = None
_cache_ts: float = 0.0
TTL_S = 5.0


def _env_flag(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes")


def _first_env(*keys: str) -> str:
    for k in keys:
        v = os.getenv(k)
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _build_exchange_sync() -> Any | None:
    import ccxt  # noqa: PLC0415

    key = _first_env(
        "BYBIT_API_KEY",
        "VITE_BYBIT_API_KEY",
        "BYBIT_API_KEY_DEMO",
        "VITE_BYBIT_API_KEY_DEMO",
    )
    sec = _first_env(
        "BYBIT_API_SECRET",
        "VITE_BYBIT_API_SECRET",
        "BYBIT_API_SECRET_DEMO",
        "VITE_BYBIT_API_SECRET_DEMO",
    )
    if not key or not sec:
        return None
    ex = ccxt.bybit(
        {
            "apiKey": key,
            "secret": sec,
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        }
    )
    use_demo = _env_flag("BYBIT_USE_DEMO")
    use_testnet = _env_flag("BYBIT_USE_TESTNET")
    if use_demo and use_testnet:
        raise RuntimeError("set only one: BYBIT_USE_DEMO or BYBIT_USE_TESTNET")
    if use_demo:
        ex.enable_demo_trading(True)
        logger.info("[balance] Bybit mode=demo")
    elif use_testnet:
        ex.set_sandbox_mode(True)
        logger.info("[balance] Bybit mode=testnet")
    else:
        logger.info("[balance] Bybit mode=mainnet")
    return ex


def _get_exchange() -> Any | None:
    global _exchange
    with _lock:
        if _exchange is _MISSING:
            ex = _build_exchange_sync()
            _exchange = _DISABLED if ex is None else ex
        if _exchange is _DISABLED:
            return None
        return _exchange


def get_sync_bybit() -> Any | None:
    """Same instance as `fetch_balance` / ohlcv when API keys are set; else `None` (public ohlcv uses its own)."""
    return _get_exchange()


def has_bybit_api_credentials() -> bool:
    k = _first_env(
        "BYBIT_API_KEY",
        "VITE_BYBIT_API_KEY",
        "BYBIT_API_KEY_DEMO",
        "VITE_BYBIT_API_KEY_DEMO",
    )
    s = _first_env(
        "BYBIT_API_SECRET",
        "VITE_BYBIT_API_SECRET",
        "BYBIT_API_SECRET_DEMO",
        "VITE_BYBIT_API_SECRET_DEMO",
    )
    return bool(k and s)


def _total_in_quote(bal: dict, quote: str) -> float | None:
    q = bal.get(quote)
    if isinstance(q, dict):
        t = q.get("total")
        if t is not None:
            try:
                return float(t)
            except (TypeError, ValueError):
                pass
        fr, us = q.get("free"), q.get("used")
        if fr is not None and us is not None:
            try:
                v = float(fr) + float(us)
                if v > 0:
                    return v
            except (TypeError, ValueError):
                pass
    totals = bal.get("total")
    if isinstance(totals, dict) and quote in totals:
        try:
            return float(totals[quote])
        except (TypeError, ValueError):
            pass
    return None


def fetch_total_equity_sync(quote: str) -> float | None:
    global _logged_balance_dump
    ex = _get_exchange()
    if ex is None:
        return None
    q = quote.upper()
    bal = ex.fetch_balance()
    v = _total_in_quote(bal, q)
    if v is None and not _logged_balance_dump:
        _logged_balance_dump = True
        if isinstance(bal, dict):
            logger.warning(
                "[balance] no %s total; balance top-level keys=%s (set BYBIT keys on the worker process for [feed] balance)",
                q,
                list(bal.keys())[:40],
            )
        else:
            logger.warning("[balance] unexpected fetch_balance type: %s", type(bal))
    return v


_logged_first_ok = False
_logged_balance_dump = False


def get_cached_equity_sync(quote: str) -> float | None:
    """Return total balance in *quote* (e.g. USDT for BTC/USDT), cached TTL_S."""
    global _cache_quote, _cache_val, _cache_ts, _logged_first_ok
    now = time.monotonic()
    q = quote.upper()
    with _lock:
        if _cache_val is not None and _cache_quote == q and (now - _cache_ts) < TTL_S:
            return _cache_val
    try:
        v = fetch_total_equity_sync(q)
    except Exception as e:  # noqa: BLE001
        logger.warning("[balance] fetch failed: %s", e)
        with _lock:
            return _cache_val if _cache_quote == q else None
    with _lock:
        _cache_ts = time.monotonic()
        if v is not None:
            _cache_val = v
            _cache_quote = q
        # if v is None, still refresh _cache_ts to avoid hammering Bybit every tick
    if v is not None and not _logged_first_ok:
        _logged_first_ok = True
        logger.info(
            "[balance] OK: total %s in %s (ccxt fetch_balance, same as worker account_equity)",
            f"{v:.4f}",
            q,
        )
    return v
