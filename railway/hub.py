"""
Execution Hub: Bybit watch_ticker -> Redis market_data:{pair}, consume order_signals, risk+exec.
Run: python -m railway.hub
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import ccxt.async_support as ccxta
from dotenv import load_dotenv
from supabase import Client

from railway.lib.bot_params import parse_bot_params
from railway.lib.redis_client import make_redis_client
from railway.lib.supabase_client import make_supabase_for_hub

load_dotenv()

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(line_buffering=True)
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [HUB] %(message)s",
    force=True,
)
logger = logging.getLogger("hub")

STALE_S = 30.0
SIG_TTL = 300.0
MAX_SEEN = 10_000
MAX_FAIL_BEFORE_STALE = 10
SIGNALS_PER_MIN_WARN = 10


@dataclass
class _Hub:
    redis: Any
    supabase: Client
    exchange: Any
    pairs_desired: set[str] = field(default_factory=set)
    watch_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    last_tick_s: dict[str, float] = field(default_factory=dict)
    last_prices: dict[str, float] = field(default_factory=dict)
    seen_ids: OrderedDict[str, float] = field(default_factory=OrderedDict)
    prev_health: str | None = None
    signal_bursts: dict[str, deque] = field(default_factory=dict)  # bot_id -> last emit times
    _sig_queue: asyncio.Queue | None = None
    _stale_published: bool = False

    def _prune_sig_cache(self) -> None:
        now = time.time()
        while self.seen_ids and len(self.seen_ids) > MAX_SEEN:
            self.seen_ids.popitem(last=False)
        for k, t in list(self.seen_ids.items()):
            if now - t > SIG_TTL:
                del self.seen_ids[k]

    def _take_id(self, sid: str) -> bool:
        if not sid or sid in self.seen_ids:
            return False
        now = time.time()
        self.seen_ids[sid] = now
        self._prune_sig_cache()
        return True

    def _bump_rate(self, bot: str) -> bool:
        """Log warning if > N signals/min. Returns always True (continue)."""
        now = time.time()
        d = self.signal_bursts.setdefault(bot, deque())
        while d and now - d[0] > 60:
            d.popleft()
        d.append(now)
        if len(d) > SIGNALS_PER_MIN_WARN:
            logger.warning("bot %s: %d signals/60s (warn>%d)", bot, len(d), SIGNALS_PER_MIN_WARN)
        return True

    def is_healthy(self) -> bool:
        if not self.pairs_desired:
            return True
        now = time.time()
        for p in self.pairs_desired:
            ts = self.last_tick_s.get(p, 0.0)
            if now - ts > STALE_S:
                return False
        return True

    def health_reason(self) -> str:
        if not self.pairs_desired:
            return "no_active_pairs"
        for p in self.pairs_desired:
            if time.time() - self.last_tick_s.get(p, 0) > STALE_S:
                return f"stale_ws:{p}"
        return "ws_ok"

    async def refresh_pairs(self) -> set[str]:
        def _run():
            r = self.supabase.table("bots").select("trading_pair").eq("status", "running").execute()
            return {row["trading_pair"] for row in (r.data or [])}

        return await asyncio.to_thread(_run)

    def publish_tick(self, pair: str, t: dict) -> None:
        now_ms = int(time.time() * 1000)
        last = t.get("last") or t.get("close")
        if last is None and isinstance(t.get("info"), dict):
            last = t["info"].get("lastPrice")
        bid = _f(t.get("bid"))
        ask = _f(t.get("ask"))
        last_f: float | None
        if last is not None:
            last_f = float(last)
        elif bid and ask:
            last_f = (float(bid) + float(ask)) / 2.0
        else:
            last_f = None
        if last_f is None:
            logger.debug("no last/bid/ask for %s — skip pub", pair)
            return
        self.last_prices[pair] = last_f
        last_qty = t.get("baseVolume")
        if last_qty is None and isinstance(t.get("info"), dict):
            last_qty = t.get("info", {}).get("baseVol")
        payload = {
            "pair": pair,
            "price": last_f,
            "bid": bid,
            "ask": ask,
            "last_qty": _f(last_qty) if last_qty is not None else None,
            "timestamp_ms": int(t.get("timestamp") or now_ms),
            "hub_published_at_ms": now_ms,
            "source": "bybit_ws_v5",
        }
        self.last_tick_s[pair] = time.time()
        self._stale_published = False
        ch = f"market_data:{pair}"
        self.redis.publish(ch, json.dumps(payload, default=_json_ser))

    async def watch_ticker(self, pair: str) -> None:
        backoff = 1.0
        fail_streak = 0
        while True:
            if pair not in self.pairs_desired:
                return
            try:
                t = await self.exchange.watch_ticker(pair)
                backoff = 1.0
                fail_streak = 0
                self.publish_tick(pair, t)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                fail_streak += 1
                logger.warning("watch_ticker %s: %s sleep %.1fs fail=%d", pair, e, backoff, fail_streak)
                if fail_streak >= MAX_FAIL_BEFORE_STALE and not self._stale_published:
                    self.redis.publish(
                        "market_data_stale",
                        json.dumps(
                            {
                                "pair": pair,
                                "reason": "reconnect",
                                "published_at_ms": int(time.time() * 1000),
                            }
                        ),
                    )
                    self._stale_published = True
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def reconciler(self) -> None:
        while True:
            try:
                d = await self.refresh_pairs()
                self.pairs_desired = d
                for p in d:
                    if p not in self.watch_tasks:
                        self.watch_tasks[p] = asyncio.create_task(self.watch_ticker(p), name=f"watch_{p}")
                        logger.info("started watcher %s", p)
                for p in list(self.watch_tasks):
                    if p not in d:
                        t = self.watch_tasks.pop(p, None)
                        if t:
                            t.cancel()
                            with contextlib.suppress(asyncio.CancelledError, Exception):
                                await t
                        logger.info("stopped watcher %s", p)
            except Exception as e:  # noqa: BLE001
                logger.exception("reconciler: %s", e)
            await asyncio.sleep(10.0)

    def _thread_sub_order_signals(self, loop: asyncio.AbstractEventLoop) -> None:
        r = make_redis_client()
        ps = r.pubsub(ignore_subscribe_messages=True)
        ps.subscribe("order_signals")
        for msg in ps.listen():
            if not msg or msg.get("type") != "message":
                continue
            d = msg.get("data")
            if d and self._sig_queue is not None:
                loop.call_soon_threadsafe(self._sig_queue.put_nowait, d)

    async def handle_signal(self, raw: str) -> None:
        try:
            s: dict = json.loads(raw)
        except Exception:  # noqa: BLE001
            logger.warning("dropped: bad json")
            return
        sid = s.get("signal_id")
        if not sid:
            logger.warning("dropped: no signal_id")
            return
        if not self._take_id(str(sid)):
            logger.info("duplicate signal ignored: %s", sid)
            return
        self._bump_rate(str(s.get("bot_id", "")))
        bot = await self._get_bot(s.get("bot_id"))
        if not bot:
            logger.warning("unknown bot %s", s.get("bot_id"))
            return
        st = (bot.get("status") or "").lower()
        if st != "running":
            logger.info("bot %s status=%s ignore", bot.get("id"), st)
            return

        try:
            amt = float(s["amount"])
        except (TypeError, KeyError, ValueError):
            logger.warning("bad amount")
            return
        caps = parse_bot_params(bot.get("params"))
        mx = float(caps.get("max_order_size") or 0)
        if amt <= 0:
            logger.warning("amount <= 0")
            return
        if mx > 0 and amt > mx:
            logger.warning("amount %s > params.max_order_size %s", amt, mx)
            await self._mark_error(bot["id"], f"invalid amount {amt}")
            return
        pair = s.get("pair", "")
        lp = self.last_prices.get(pair)
        if not lp or lp <= 0:
            lp = await self._refetch_ticker_price(pair)
        if not lp:
            logger.warning("no price for %s defer", pair)
            return
        notional = amt * float(lp)
        mnot = float(caps.get("max_notional_usd") or 0)
        if mnot and notional > mnot:
            logger.warning("notional %.2f > params.max_notional_usd %s", notional, mnot)
            return

        oc = await self._open_trades_count(bot["id"])
        mpos = int(caps.get("max_open_positions") or 0)
        act = s.get("action", "")
        if mpos > 0 and act in ("BUY", "SELL") and oc >= mpos:
            logger.info("bot at max open positions: %d", oc)
            return

        ok, why = await self._balance_check(pair, s.get("action", ""), amt, float(lp))
        if not ok:
            logger.warning("balance check fail: %s", why)
            return

        try:
            o = await self._exec_order(s, float(lp))
        except Exception as e:  # noqa: BLE001
            logger.exception("order failed: %s", e)
            await self._mark_error(bot["id"], f"exec: {e}")
            await self._ins_trade_rej(bot, s, str(e))
            return
        await self._ins_trade_open(bot, s, o, float(lp))

    async def _get_bot(self, bid: str | None) -> dict | None:
        if not bid:
            return None

        def _r():
            o = self.supabase.table("bots").select("*").eq("id", bid).limit(1).execute()
            d = o.data
            return d[0] if d else None

        return await asyncio.to_thread(_r)

    async def _open_trades_count(self, bot_id: str) -> int:
        def _c():
            o = (
                self.supabase.table("trades")
                .select("id", count="exact")
                .eq("bot_id", bot_id)
                .eq("status", "OPEN")
                .execute()
            )
            return int(o.count or 0) if o.count is not None else len(o.data or [])

        return await asyncio.to_thread(_c)

    async def _refetch_ticker_price(self, pair: str) -> float | None:
        try:
            t = await self.exchange.fetch_ticker(pair)
            last = t.get("last")
            if last is not None:
                self.last_prices[pair] = float(last)
                return float(last)
        except Exception as e:  # noqa: BLE001
            logger.warning("refetch_ticker %s: %s", pair, e)
        return None

    async def _balance_check(
        self, pair: str, action: str, amount: float, last_px: float
    ) -> tuple[bool, str]:
        try:
            b = await self.exchange.fetch_balance()
        except Exception as e:  # noqa: BLE001
            return False, f"fetch_balance:{e}"
        if not b:
            return True, "no_balance_obj"
        base, quote = pair.split("/") if "/" in pair else ("", "")
        notional = amount * last_px
        a = (action or "").upper()
        if a in ("BUY", "CLOSE_SHORT"):
            free = _ccxt_free(b, quote)
            if free < notional * 0.999:
                return False, f"need {quote} free {free} < {notional}"
        if a in ("SELL", "CLOSE_LONG"):
            free2 = _ccxt_free(b, base)
            if free2 < amount * 0.999:
                return False, f"need {base} free {free2} < {amount}"
        return True, "ok"

    async def _exec_order(self, s: dict, last_price: float) -> dict:
        a = (s.get("action") or "").upper()
        side = {"BUY": "buy", "SELL": "sell", "CLOSE_LONG": "sell", "CLOSE_SHORT": "buy"}.get(a)
        if not side:
            raise ValueError(f"action {a}")
        pair = s.get("pair")
        amt = float(s.get("amount", 0))
        t = s.get("type", "MARKET")
        p = s.get("price")
        if (t or "").upper() == "MARKET" or t is None:
            return await self.exchange.create_market_order(pair, side, amt, {})
        return await self.exchange.create_limit_order(
            pair, side, amt, float(p) if p else last_price, {}
        )

    async def _ins_trade_open(self, bot: dict, sig: dict, o: dict, last_px: float) -> None:
        act = (sig.get("action") or "").upper()
        dmap = {
            "BUY": "LONG",
            "SELL": "SHORT",
            "CLOSE_LONG": "LONG",
            "CLOSE_SHORT": "SHORT",
        }
        pr = o.get("average") or o.get("price")
        epx = float(pr) if pr else last_px

        def _i():
            self.supabase.table("trades").insert(
                {
                    "signal_id": str(sig.get("signal_id")),
                    "bot_id": bot["id"],
                    "versao_id": sig.get("version_id"),
                    "par_negociacao": sig.get("pair"),
                    "direcao": dmap.get(act, "LONG"),
                    "preco_entrada": epx,
                    "quantity": float(sig.get("amount", 0)),
                    "notional_usd": float(sig.get("amount", 0)) * last_px,
                    "exchange_order_id": str(o.get("id", "")) or None,
                    "status": "OPEN",
                    "opened_at": _iso_now(),
                    "resultado": "OPEN",
                }
            ).execute()

        await asyncio.to_thread(_i)

    async def _ins_trade_rej(self, bot: dict, s: dict, err: str) -> None:
        def _i():
            try:
                self.supabase.table("trades").insert(
                    {
                        "signal_id": s.get("signal_id"),
                        "bot_id": bot.get("id"),
                        "versao_id": s.get("version_id"),
                        "par_negociacao": s.get("pair", "UNKNOWN"),
                        "direcao": "LONG",
                        "status": "REJECTED",
                        "preco_entrada": None,
                        "resultado": f"REJECT: {err[:200]}",
                    }
                ).execute()
            except Exception as e2:  # noqa: BLE001
                logger.warning("rejected row insert: %s", e2)

        await asyncio.to_thread(_i)

    async def _mark_error(self, bot_id: str, err: str) -> None:
        def _m():
            self.supabase.table("bots").update(
                {
                    "status": "error",
                    "last_error": str(err)[:2000],
                    "last_error_at": _iso_now(),
                }
            ).eq("id", bot_id).execute()

        await asyncio.to_thread(_m)

    async def consumer(self) -> None:
        if self._sig_queue is None:
            self._sig_queue = asyncio.Queue(maxsize=2000)
        loop = asyncio.get_running_loop()
        threading.Thread(target=self._thread_sub_order_signals, args=(loop,), daemon=True).start()
        while True:
            raw = await self._sig_queue.get()
            try:
                await self.handle_signal(raw)
            except Exception:  # noqa: BLE001
                logger.exception("handle_signal error")

    async def hub_status_loop(self) -> None:
        while True:
            h = "healthy" if self.is_healthy() else "degraded"
            if h != self.prev_health:
                self.prev_health = h
                p = {
                    "status": h,
                    "reason": self.health_reason(),
                    "published_at_ms": int(time.time() * 1000),
                }
                self.redis.publish("hub:status", json.dumps(p))
                logger.info("hub:status %s", p)
            await asyncio.sleep(5.0)

    async def run(self) -> None:
        await self.exchange.load_markets()
        await asyncio.gather(
            self.reconciler(), self.consumer(), self.hub_status_loop()
        )


def _ccxt_free(bal: Any, ccy: str) -> float:
    x = bal.get(ccy) if bal else None
    if x is None:
        return 0.0
    if isinstance(x, dict):
        return float(x.get("free", 0) or 0.0)
    if isinstance(x, (int, float, str)):
        return float(x)
    return 0.0


def _f(x) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _json_ser(x):
    if isinstance(x, (int, float, str, type(None), bool)):
        return x
    if hasattr(x, "item"):
        try:
            return float(x.item())  # numpy
        except Exception:  # noqa: BLE001
            pass
    return str(x)


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _env_flag(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes")


def _first_env(*keys: str) -> str:
    for k in keys:
        v = os.getenv(k)
        if v and str(v).strip():
            return str(v).strip()
    return ""


def build_exchange() -> Any:
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
    ex = ccxta.bybit(
        {
            "apiKey": key,
            "secret": sec,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )
    # Demo trading (paper on api-demo.*) and testnet (testnet.bybit keys) are different; CCXT rejects both.
    use_demo = _env_flag("BYBIT_USE_DEMO")
    use_testnet = _env_flag("BYBIT_USE_TESTNET")
    if use_demo and use_testnet:
        raise RuntimeError("set only one: BYBIT_USE_DEMO (demo keys) or BYBIT_USE_TESTNET (testnet keys)")
    if use_demo:
        ex.enable_demo_trading(True)
        logger.info("Bybit mode=demo (api-demo); unset BYBIT_USE_TESTNET")
    elif use_testnet:
        ex.set_sandbox_mode(True)
        logger.info("Bybit mode=testnet")
    else:
        logger.info("Bybit mode=mainnet; set BYBIT_USE_DEMO=true for demo API keys")
    return ex


async def main() -> None:
    r = make_redis_client()
    sb = make_supabase_for_hub()
    ex = build_exchange()
    hub = _Hub(redis=r, supabase=sb, exchange=ex, _sig_queue=None)
    try:
        await hub.run()
    finally:
        try:
            await ex.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    asyncio.run(main())
