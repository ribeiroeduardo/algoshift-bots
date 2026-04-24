"""Fase1 mock: sub BTC/USDT, every 5 ticks send mock BUY to order_signals."""
from __future__ import annotations

import json
import logging
import time
import uuid

from railway.lib.redis_client import make_redis_client

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [WORKER-V1] %(message)s", force=True
)
logger = logging.getLogger(__name__)


def main() -> None:
    r = make_redis_client()
    p = r.pubsub()
    p.subscribe("market_data:BTC/USDT")
    logger.info("sub market_data:BTC/USDT")
    n = 0
    for msg in p.listen():
        if msg.get("type") != "message":
            continue
        tick = json.loads(msg["data"])
        n += 1
        logger.info("tick#%d price=%.2f", n, float(tick["price"]))
        if n % 5:
            continue
        sig = {
            "signal_id": str(uuid.uuid4()),
            "bot_id": "mock-bot-v1",
            "version_id": "mock",
            "action": "BUY",
            "type": "MARKET",
            "pair": "BTC/USDT",
            "amount": 0.001,
            "reason": "mock_v1",
            "emitted_at_ms": int(time.time() * 1000),
        }
        r.publish("order_signals", json.dumps(sig))
        logger.info("published BUY signal_id=%s", sig["signal_id"])


if __name__ == "__main__":
    main()
