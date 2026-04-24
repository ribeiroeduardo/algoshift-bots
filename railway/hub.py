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
from railway.lib.trading_pair_ccxt import (
    base_quote_for_balance,
    normalize_trading_pair,
    trading_pair_to_ccxt,
)

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
# When CCXT has no watch_ticker for Bybit (e.g. demo), fall back to REST polling.
# Default 0.35s between successful fetches (raise if Bybit rate-limits). Logs: HUB_POLL_LOG_SEC.
POLL_INTERVAL_SEC = float((os.getenv("HUB_POLL_INTERVAL_SEC") or "0.35").strip() or "0.35")
POLL_LOG_INTERVAL_SEC = float((os.getenv("HUB_POLL_LOG_SEC") or "1.0").strip() or "1.0")
FETCH_TICKER_TIMEOUT_SEC = float((os.getenv("HUB_FETCH_TIMEOUT_SEC") or "25.0").strip() or "25.0")


@dataclass
class _Hub:
    redis: Any
    supabase: Client
    exchange: Any
    pairs_desired: set[str] = field(default_factory=set)
    pair_market: dict[str, str] = field(default_factory=dict)
    watch_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    last_tick_s: dict[str, float] = field(default_factory=dict)
    last_prices: dict[str, float] = field(default_factory=dict)
    seen_ids: OrderedDict[str, float] = field(default_factory=OrderedDict)
    prev_health: str | None = None
    signal_bursts: dict[str, deque] = field(default_factory=dict)  # bot_id -> last emit times
    _sig_queue: asyncio.Queue | None = None
    _stale_published: bool = False
    _poll_log_at: dict[str, float] = field(default_factory=dict)

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

    async def refresh_pairs(self) -> dict[str, str]:
        """display_ticker -> market_type (first running bot wins on conflict)."""

        def _run() -> dict[str, str]:
            r = (
                self.supabase.table("bots")
                .select("trading_pair", "market_type")
                .eq("status", "running")
                .execute()
            )
            out: dict[str, str] = {}
            for row in r.data or []:
                p = normalize_trading_pair(str(row.get("trading_pair") or ""))
                if not p:
                    continue
                mt = (row.get("market_type") or "linear").lower()
                if mt not in ("spot", "linear", "inverse"):
                    mt = "linear"
                if p not in out:
                    out[p] = mt
                elif out[p] != mt:
                    logger.warning(
                        "running bots disagree market_type for %s (%s vs %s); keeping %s",
                        p,
                        out[p],
                        mt,
                        out[p],
                    )
            return out

        return await asyncio.to_thread(_run)

    def publish_tick(self, pair: str, t: dict, *, source: str = "bybit_ws_v5") -> None:
        now_ms = int(time.time() * 1000)
        last_f, bid, ask = _ticker_prices(t)
        if last_f is None:
            keys = list(t.keys()) if isinstance(t, dict) else []
            logger.warning(
                "skip publish %s: no price in ticker (keys=%s) source=%s",
                pair,
                keys[:25],
                source,
            )
            return
        self.last_prices[pair] = last_f
        if source == "bybit_rest_poll":
            ts = time.time()
            prev = self._poll_log_at.get(pair, 0.0)
            if ts - prev >= POLL_LOG_INTERVAL_SEC:
                self._poll_log_at[pair] = ts
                logger.info(
                    "market_data %s price=%.2f bid=%s ask=%s (rest poll; kline/candle vol is fetched in worker)",
                    pair,
                    last_f,
                    bid,
                    ask,
                )
            logger.debug("market_data %s price=%.2f (rest poll)", pair, last_f)
        info = t.get("info") if isinstance(t.get("info"), dict) else {}
        last_tr_base = _f(
            t.get("lastTraded")
            or t.get("lastTradeAmount")
            or info.get("lastTraded")
            or info.get("size")
        )
        payload = {
            "pair": pair,
            "price": last_f,
            "bid": bid,
            "ask": ask,
            "last_qty": last_tr_base,
            "timestamp_ms": int(t.get("timestamp") or now_ms),
            "hub_published_at_ms": now_ms,
            "source": source,
        }
        self.last_tick_s[pair] = time.time()
        self._stale_published = False
        ch = f"market_data:{pair}"
        self.redis.publish(ch, json.dumps(payload, default=_json_ser))

    def _watch_unsupported(self, err: BaseException) -> bool:
        m = str(err).lower()
        return "not supported" in m or "watchticker" in m

    async def _poll_ticker(self, pair: str) -> None:
        backoff = 1.0
        fail_streak = 0
        interval = max(0.15, POLL_INTERVAL_SEC)
        timeout = max(5.0, FETCH_TICKER_TIMEOUT_SEC)
        logger.info(
            "poll_ticker: loop %s interval=%.1fs fetch_timeout=%.1fs",
            pair,
            interval,
            timeout,
        )
        while pair in self.pairs_desired:
            mt = self.pair_market.get(pair, "linear")
            ccxt_sym = trading_pair_to_ccxt(pair, mt)
            if not ccxt_sym:
                logger.error("poll_ticker: no CCXT symbol for %s market_type=%s", pair, mt)
                await asyncio.sleep(5.0)
                continue
            try:
                t = await asyncio.wait_for(self.exchange.fetch_ticker(ccxt_sym), timeout=timeout)
                backoff = 1.0
                fail_streak = 0
                self.publish_tick(pair, t, source="bybit_rest_poll")
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                fail_streak += 1
                logger.warning(
                    "poll_ticker %s: fetch_ticker timed out after %.1fs (fail=%d) sleep %.1fs",
                    pair,
                    timeout,
                    fail_streak,
                    backoff,
                )
                if fail_streak >= MAX_FAIL_BEFORE_STALE and not self._stale_published:
                    self.redis.publish(
                        "market_data_stale",
                        json.dumps(
                            {
                                "pair": pair,
                                "reason": "poll_timeout",
                                "published_at_ms": int(time.time() * 1000),
                            }
                        ),
                    )
                    self._stale_published = True
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            except Exception as e:  # noqa: BLE001
                fail_streak += 1
                logger.warning("poll_ticker %s: %s sleep %.1fs fail=%d", pair, e, backoff, fail_streak)
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
            else:
                await asyncio.sleep(interval)

    async def watch_ticker(self, pair: str) -> None:
        backoff = 1.0
        fail_streak = 0
        while True:
            if pair not in self.pairs_desired:
                return
            try:
                mt = self.pair_market.get(pair, "linear")
                ccxt_sym = trading_pair_to_ccxt(pair, mt)
                if not ccxt_sym:
                    logger.error("watch_ticker: no CCXT symbol for %s market_type=%s", pair, mt)
                    await asyncio.sleep(5.0)
                    continue
                t = await self.exchange.watch_ticker(ccxt_sym)
                backoff = 1.0
                fail_streak = 0
                self.publish_tick(pair, t)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                if self._watch_unsupported(e):
                    logger.info(
                        "watch_ticker not supported for %s (%s) — using REST poll every %.1fs",
                        pair,
                        e,
                        max(0.15, POLL_INTERVAL_SEC),
                    )
                    await self._poll_ticker(pair)
                    return
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
                self.pairs_desired = set(d.keys())
                self.pair_market = d
                for p in self.pairs_desired:
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
        pair = normalize_trading_pair(str(s.get("pair", "") or ""))
        if not pair:
            logger.warning("dropped: empty pair")
            return
        mt_bot = (bot.get("market_type") or "linear").lower()
        if mt_bot not in ("spot", "linear", "inverse"):
            mt_bot = "linear"
        lp = self.last_prices.get(pair)
        if not lp or lp <= 0:
            lp = await self._refetch_ticker_price(pair, mt_bot)
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

        ok, why = await self._balance_check(pair, s.get("action", ""), amt, float(lp), mt_bot)
        if not ok:
            logger.warning("balance check fail: %s", why)
            return

        try:
            o = await self._exec_order(s, float(lp), mt_bot)
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

    async def _refetch_ticker_price(self, pair: str, market_type: str) -> float | None:
        try:
            ccxt_sym = trading_pair_to_ccxt(pair, market_type)
            if not ccxt_sym:
                return None
            t = await self.exchange.fetch_ticker(ccxt_sym)
            last = t.get("last")
            if last is not None:
                self.last_prices[pair] = float(last)
                return float(last)
        except Exception as e:  # noqa: BLE001
            logger.warning("refetch_ticker %s: %s", pair, e)
        return None

    async def _balance_check(
        self, pair: str, action: str, amount: float, last_px: float, market_type: str
    ) -> tuple[bool, str]:
        try:
            b = await self.exchange.fetch_balance()
        except Exception as e:  # noqa: BLE001
            return False, f"fetch_balance:{e}"
        if not b:
            return True, "no_balance_obj"
        base, quote = base_quote_for_balance(pair, market_type)
        if not base or not quote:
            return False, f"cannot parse base/quote from pair={pair!r}"
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

    async def _exec_order(self, s: dict, last_price: float, market_type: str) -> dict:
        a = (s.get("action") or "").upper()
        side = {"BUY": "buy", "SELL": "sell", "CLOSE_LONG": "sell", "CLOSE_SHORT": "buy"}.get(a)
        if not side:
            raise ValueError(f"action {a}")
        pair_disp = normalize_trading_pair(str(s.get("pair") or ""))
        ccxt_sym = trading_pair_to_ccxt(pair_disp, market_type)
        if not ccxt_sym:
            raise ValueError(f"no CCXT symbol for pair={pair_disp!r} market_type={market_type!r}")
        amt = float(s.get("amount", 0))
        t = s.get("type", "MARKET")
        p = s.get("price")
        if (t or "").upper() == "MARKET" or t is None:
            return await self.exchange.create_market_order(ccxt_sym, side, amt, {})
        return await self.exchange.create_limit_order(
            ccxt_sym, side, amt, float(p) if p else last_price, {}
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


def _ticker_prices(t: dict) -> tuple[float | None, float | None, float | None]:
    """CCXT unified ticker + Bybit `info` fallbacks → (last, bid, ask)."""
    if not isinstance(t, dict):
        return None, None, None
    info = t.get("info") if isinstance(t.get("info"), dict) else {}
    last = t.get("last") or t.get("close")
    if last is None and info:
        last = (
            info.get("lastPrice")
            or info.get("last")
            or info.get("indexPrice")
            or info.get("markPrice")
        )
    bid = _f(t.get("bid"))
    ask = _f(t.get("ask"))
    if bid is None and info:
        bid = _f(info.get("bid1Price") or info.get("bidPrice") or info.get("b"))
    if ask is None and info:
        ask = _f(info.get("ask1Price") or info.get("askPrice") or info.get("a"))
    last_f: float | None = None
    if last is not None:
        try:
            last_f = float(last)
        except (TypeError, ValueError):
            last_f = None
    if last_f is None and bid is not None and ask is not None:
        last_f = (bid + ask) / 2.0
    return last_f, bid, ask


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
