"""Parse bots.params JSON for worker signals and optional hub risk caps."""
from __future__ import annotations

import json
import os
from typing import Any


def resolve_signal_amount(strategy: object | None, raw_params: Any) -> float:
    """
    Order size for Redis order_signals: strategy code first (attributes or
    get_signal_amount()), then optional bots.params JSON for backward compatibility.
    """
    if strategy is not None:
        for attr in ("signal_amount", "order_size", "amount", "size"):
            v = getattr(strategy, attr, None)
            if v is not None:
                try:
                    f = float(v)
                    if f > 0:
                        return f
                except (TypeError, ValueError):
                    pass
        fn = getattr(strategy, "get_signal_amount", None)
        if callable(fn):
            try:
                f = float(fn())
                if f > 0:
                    return f
            except (TypeError, ValueError):
                pass
    p = parse_bot_params(raw_params)
    return float(p.get("signal_amount") or p.get("amount") or 0.0)


def parse_bot_params(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            o = json.loads(s)
            return o if isinstance(o, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def resolve_ohlcv_timeframe(params: dict, strategy_hint: str | None) -> str:
    """
    Kline interval for Bybit/candle fields in market_data. Priority:
    1) bots.params ohlcv_timeframe / ohlcv_tf / candle_timeframe / kline_timeframe
    2) module-level hint from strategy code (e.g. BASE_TF = '1min' -> '1m')
    3) env WORKER_OHLCV_TIMEFRAME
    4) default 15m
    """
    p = params or {}
    for key in ("ohlcv_timeframe", "ohlcv_tf", "candle_timeframe", "kline_timeframe"):
        v = p.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    if strategy_hint and str(strategy_hint).strip():
        return str(strategy_hint).strip()
    return (os.getenv("WORKER_OHLCV_TIMEFRAME") or "15m").strip() or "15m"
