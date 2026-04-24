"""Fase1 mock: publish fake ticks, log order_signals (redis ping-pong)."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

from railway.lib.redis_client import make_redis_client

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [HUB-V1] %(message)s", force=True
)
logger = logging.getLogger(__name__)


def _signal_listener(r) -> None:
    pubsub = r.pubsub()
    pubsub.subscribe("order_signals")
    logger.info("subscribed order_signals")
    for msg in pubsub.listen():
        if msg.get("type") != "message":
            continue
        try:
            logger.info("SIGNAL: %s", json.loads(msg["data"]))
        except Exception:  # noqa: BLE001
            logger.exception("invalid signal json")


async def main() -> None:
    r = make_redis_client()
    threading.Thread(target=_signal_listener, args=(r,), daemon=True).start()
    price = 65000.0
    candle_forms = 0.0
    while True:
        price += 0.5
        candle_forms += 0.0002
        p = {
            "pair": "BTC/USDT",
            "price": price,
            "bid": price - 0.5,
            "ask": price + 0.5,
            "last_qty": None,
            "candle_ohlcv_timeframe": "15m",
            "candle_open_time_ms": int((time.time() // 900) * 900 * 1000),
            "candle_base_volume": candle_forms,
            "candle_base_volume_delta": 0.0002,
            "candle_closed_vol_ma_10": 1.0,
            "timestamp_ms": int(time.time() * 1000),
            "hub_published_at_ms": int(time.time() * 1000),
            "source": "hub_v1_mock",
        }
        n = r.publish("market_data:BTC/USDT", json.dumps(p))
        logger.info("published tick price=%.2f sub=%d", price, n)
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
