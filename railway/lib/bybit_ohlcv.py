"""
Bybit OHLCV (ccxt) — *per-candle* base **trade** volume from `fetch_ohlcv` (not 24h ticker vol).

* ``candle_base_volume`` — base volume **so far** in the **current (forming) kline** (CCXT ohlcv[-1][5]).
* ``candle_base_volume_delta`` — increase in that same cumulative since the last *HTTP* fetch
  (same kline; 0 if throttled between polls).
* ``candle_closed_vol_ma_10`` — mean of the last 10 *closed* klines’ base vol (if enough history).

Uses authenticated Bybit (demo / testnet / main) if keys are set, else a public (no key) client for klines.
"""
from __future__ import annotations

import logging
import os
import statistics
import threading
import time
from typing import Any

from railway.lib.bybit_balance import get_sync_bybit

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_min_fetch = float((os.getenv("WORKER_OHLCV_MIN_S") or "0.6").strip() or "0.6")
_last_fetch_m: float = 0.0
_ohlcv_cache: list = []
_prev_k: tuple[str, str, int, float] | None = None
_public: Any = None


def _to_f(x) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _public_ex() -> Any:
    global _public
    import ccxt  # noqa: PLC0415

    with _lock:
        if _public is not None:
            return _public
    ex = ccxt.bybit(
        {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )
    with _lock:
        _public = ex
    return ex


def _ex_for_ohlcv() -> Any:
    ex = get_sync_bybit()
    return ex if ex is not None else _public_ex()


def get_candle_volume_snapshot(pair: str, timeframe: str) -> dict:
    """
    Throttled fetches. Returns a dict merged into the worker’s ``market_data`` for the strategy.
    """
    global _last_fetch_m, _ohlcv_cache, _prev_k
    now = time.monotonic()
    ohlcv: list | None = None
    did_fetch = False
    with _lock:
        cool = (now - _last_fetch_m) < _min_fetch
        throttled = cool and bool(_ohlcv_cache)
    if throttled and _ohlcv_cache is not None:
        ohlcv = _ohlcv_cache
    else:
        ex = _ex_for_ohlcv()
        try:
            ohlcv = ex.fetch_ohlcv(pair, timeframe, limit=20)
        except Exception as e:  # noqa: BLE001
            logger.warning("[ohlcv] fetch_ohlcv %s %s: %s", pair, timeframe, e)
            return {
                "candle_ohlcv_timeframe": timeframe,
                "candle_ohlcv_error": str(e)[:200],
            }
        did_fetch = True
        with _lock:
            _ohlcv_cache = ohlcv
            _last_fetch_m = time.monotonic()

    if not ohlcv:
        return {
            "candle_ohlcv_timeframe": timeframe,
        }

    form = ohlcv[-1]
    t_open = int(form[0])
    cum = _to_f(form[5]) or 0.0
    dvol = 0.0
    old = _prev_k
    if did_fetch and old and old[0] == pair and old[1] == timeframe:
        if old[2] == t_open and cum >= old[3]:
            dvol = float(cum - old[3])
    if did_fetch:
        with _lock:
            _prev_k = (pair, timeframe, t_open, float(cum))

    closed: list[float] = []
    if len(ohlcv) >= 2:
        for row in ohlcv[:-1][-10:]:
            if len(row) > 5 and row[5] is not None:
                closed.append(float(_to_f(row[5]) or 0.0))
    ma10: float | None = None
    if len(closed) >= 10:
        ma10 = float(statistics.mean(closed[-10:]))

    return {
        "candle_ohlcv_timeframe": timeframe,
        "candle_open_time_ms": t_open,
        "candle_base_volume": float(cum),
        "candle_base_volume_delta": dvol,
        "candle_closed_base_volumes_10": closed,
        "candle_closed_vol_ma_10": ma10,
    }
