"""
Strategy worker: BOT_ID + Redis market_data + on_tick -> order_signals.
Optional BYBIT_API_KEY / BYBIT_API_SECRET (+ demo/testnet flags) for account balance → sizing.
Run: python -m railway.worker
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from hashlib import sha256
import threading
import time
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

from railway.lib.bot_params import parse_bot_params, resolve_ohlcv_timeframe, resolve_signal_amount
from railway.lib.bybit_balance import get_cached_equity_sync, has_bybit_api_credentials
from railway.lib.bybit_ohlcv import get_candle_volume_snapshot
from railway.lib.trading_pair_ccxt import (
    base_quote_for_balance,
    base_symbol_for_logs,
    default_trading_pair,
    trading_pair_to_ccxt,
)
from railway.lib.redis_client import make_redis_client
from railway.lib.redis_topics import ORDER_OUTCOMES
from railway.lib.strategy_loader import load_strategy_from_db
from railway.lib.supabase_client import make_supabase_for_worker

load_dotenv()
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(line_buffering=True)
    except Exception:
        pass

os.environ.setdefault("MPLBACKEND", "Agg")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - [WORKER] %(message)s", force=True
)
for _lg in ("httpx", "httpcore"):
    logging.getLogger(_lg).setLevel(logging.WARNING)
logger = logging.getLogger("worker")

FEED_LOG_SEC = float((os.getenv("WORKER_FEED_LOG_SEC") or "30.0").strip() or "30.0")


def _to_f(x) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _iso_from_ms(ms: int) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).replace(microsecond=0).isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class StrategyWorker:
    def __init__(self) -> None:
        self.bot_id = (os.getenv("BOT_ID") or "").strip()
        if not self.bot_id:
            raise RuntimeError(
                "BOT_ID missing: export BOT_ID=<uuid from public.bots.id> (Strategies UI list / Supabase)"
            )
        self.supabase = make_supabase_for_worker()
        self.redis = make_redis_client()
        self.bot_row: dict | None = None
        self.strategy = None
        self._compile_key: str | None = None
        self.last_tick_at_ms = 0
        self.last_signal_at_ms = 0
        self.ticks = 0
        self.signals = 0
        self.hub_status = "healthy"  # until msg
        self._q: asyncio.Queue | None = None
        self._q_status: asyncio.Queue | None = None
        self._q_outcomes: asyncio.Queue | None = None
        self._last_strategy_error: str | None = None
        self._last_feed_log_m: float = 0.0
        self.ohlcv_timeframe = "15m"  # set in reload() from params / strategy BASE_TF / env
        self._ohlcv_hint: str | None = None
        self._warned_no_bybit: bool = False
        self._log_until: dict[str, float] = {}

    def _warn_throttled(self, key: str, interval: float, fmt: str, *args: object) -> None:
        now = time.monotonic()
        if now < self._log_until.get(key, 0.0):
            return
        self._log_until[key] = now + interval
        logger.warning(fmt, *args)

    async def reload(self) -> None:
        r = (
            self.supabase.table("bots")
            .select(
                "id, name, strategy_id, trading_pair, market_type, status, "
                "params, last_error, content, version_number"
            )
            .eq("id", self.bot_id)
            .limit(1)
            .execute()
        )
        self.bot_row = (r.data or [None])[0]
        if not self.bot_row:
            raise RuntimeError(f"bot {self.bot_id} not found")
        raw = json.dumps(self.bot_row.get("params") or {}, sort_keys=True, default=str)
        content = self.bot_row.get("content") or ""
        compile_key = sha256(f"{content}\0{raw}".encode()).hexdigest()
        if compile_key != self._compile_key or self.strategy is None:
            inst, err, ohlc_hint = load_strategy_from_db(self.supabase, self.bot_id)
            self._ohlcv_hint = ohlc_hint
            if inst is not None:
                self.strategy = inst
                self._compile_key = compile_key
                self._last_strategy_error = None
                logger.info("strategy load bot=%s", self.bot_id)
            else:
                self._last_strategy_error = err
                logger.error("compile fail: %s", err)
                self.strategy = None
                self._compile_key = None
        self.ohlcv_timeframe = resolve_ohlcv_timeframe(
            parse_bot_params(self.bot_row.get("params")),
            self._ohlcv_hint,
        )
        st = (self.bot_row.get("status") or "").lower()
        if st == "error":
            logger.info(
                "bot %s -> error exit: status=error in DB. Set to stopped or running in Strategies UI / Supabase, then restart worker.",
                self.bot_id,
            )
            os._exit(0)
        # stopped: keep process up so UI "Start" (status=running) works without redeploy

    async def config_loop(self) -> None:
        while True:
            try:
                prev = self.bot_row.get("status") if self.bot_row else None
                await self.reload()
                cur = self.bot_row.get("status") if self.bot_row else None
                if prev and cur and prev != cur:
                    le = (self.bot_row or {}).get("last_error")
                    la = (self.bot_row or {}).get("last_error_at")
                    if (cur or "").lower() == "error":
                        logger.error(
                            "bot DB status %s -> %s last_error_at=%s last_error=%s",
                            prev,
                            cur,
                            la,
                            (str(le)[:1500] if le else ""),
                        )
                    else:
                        logger.info(
                            "bot DB status %s -> %s (last_error_at=%s snippet=%s)",
                            prev,
                            cur,
                            la,
                            (str(le)[:400] if le else ""),
                        )
            except Exception as e:  # noqa: BLE001
                logger.exception("reload: %s", e)
            await asyncio.sleep(5.0)

    def _sub_thread(self, loop: asyncio.AbstractEventLoop, pair: str) -> None:
        r = make_redis_client()
        p = r.pubsub(ignore_subscribe_messages=True)
        p.subscribe(f"market_data:{pair}")
        for msg in p.listen():
            if msg and msg.get("type") == "message" and msg.get("data") and self._q:
                loop.call_soon_threadsafe(self._q.put_nowait, msg["data"])

    def _order_outcomes_thread(self, loop: asyncio.AbstractEventLoop) -> None:
        r = make_redis_client()
        p = r.pubsub(ignore_subscribe_messages=True)
        p.subscribe(ORDER_OUTCOMES)
        logger.info("subscribed %s (hub execution results)", ORDER_OUTCOMES)
        for msg in p.listen():
            if msg and msg.get("type") == "message" and msg.get("data") and self._q_outcomes:
                loop.call_soon_threadsafe(self._q_outcomes.put_nowait, msg["data"])

    def _hub_status_thread(self, loop: asyncio.AbstractEventLoop) -> None:
        r = make_redis_client()
        p = r.pubsub(ignore_subscribe_messages=True)
        p.subscribe("hub:status")
        for msg in p.listen():
            if msg and msg.get("type") == "message" and msg.get("data") and self._q_status:
                loop.call_soon_threadsafe(self._q_status.put_nowait, msg["data"])

    async def on_tick(self, raw: str) -> None:
        t = None
        try:
            t = json.loads(raw)
        except Exception:  # noqa: BLE001
            return
        lat = int(time.time() * 1000) - int(t.get("hub_published_at_ms") or 0)
        if lat > 2000:
            logger.debug("stale %dms", lat)
            return
        if self.hub_status != "healthy" and self.hub_status is not None:
            self._warn_throttled(
                "hub_unhealthy",
                25.0,
                "[tick_blocked] hub_status=%s — ticks/signals paused until hub is healthy",
                self.hub_status,
            )
            return
        st = (self.bot_row or {}).get("status")
        if st != "running":
            le = (self.bot_row or {}).get("last_error")
            self._warn_throttled(
                f"bot_status_{st}",
                25.0,
                "[tick_blocked] bot DB status=%r (need 'running'). last_error=%s",
                st,
                (str(le)[:500] if le else ""),
            )
            return
        if not self.strategy:
            return
        self.ticks += 1
        self.last_tick_at_ms = int(time.time() * 1000)
        pair = (self.bot_row or {}).get("trading_pair") or default_trading_pair()
        pair = str(pair).strip().upper()
        mt = ((self.bot_row or {}).get("market_type") or "linear").lower()
        if mt not in ("spot", "linear", "inverse"):
            mt = "linear"
        _base, quote = base_quote_for_balance(pair, mt)
        if not quote:
            quote = "USDT"
        try:
            account_equity = await asyncio.to_thread(get_cached_equity_sync, quote)
        except Exception as e:  # noqa: BLE001
            logger.debug("account_equity: %s", e)
            account_equity = None

        ccxt_pair = trading_pair_to_ccxt(pair, mt)
        try:
            ohlc = await asyncio.to_thread(get_candle_volume_snapshot, ccxt_pair, self.ohlcv_timeframe)
        except Exception as e:  # noqa: BLE001
            logger.warning("ohlcv snapshot: %s", e)
            ohlc = {"candle_ohlcv_error": str(e)}

        if not has_bybit_api_credentials() and not self._warned_no_bybit:
            self._warned_no_bybit = True
            logger.warning(
                "No BYBIT_API_KEY / BYBIT_API_SECRET in this process: account_equity=n/a. "
                "Set the same Bybit (demo) keys on the *worker* process to log balance in [feed] "
                "(HUB only streams prices — balance is never in Hub logs).",
            )
        md: dict = {
            "price": t.get("price"),
            "bid": t.get("bid"),
            "ask": t.get("ask"),
            "timestamp": t.get("timestamp_ms") or t.get("timestamp") or 0,
            "last_qty": t.get("last_qty"),
            "account_equity": account_equity,
        }
        md.update(ohlc)
        if md["price"] is None:
            return

        now_m = time.monotonic()
        if self.ticks == 1 or (now_m - self._last_feed_log_m) >= FEED_LOG_SEC:
            self._last_feed_log_m = now_m
            eqs = f"{float(account_equity):.4f}" if account_equity is not None else "n/a"
            cbf = ohlc.get("candle_base_volume")
            cbd = ohlc.get("candle_base_volume_delta")
            ma10 = ohlc.get("candle_closed_vol_ma_10")
            t_open = ohlc.get("candle_open_time_ms")
            base_sym = base_symbol_for_logs(pair or default_trading_pair())
            err = ohlc.get("candle_ohlcv_error")
            if err and self.ticks < 3:
                logger.warning("[ohlcv] %s", err)
            logger.info(
                "[feed] %s price=%s ohlcv_tf=%s t_open=%s %s_forms_cum=%s dV_on_fetch=%s "
                "closed10_MA=%s balance_%s=%s (Bybit: kline vol + balance only on WORKER; Hub=price only)",
                pair,
                md.get("price"),
                self.ohlcv_timeframe,
                t_open,
                base_sym,
                f"{cbf:.6f}" if cbf is not None else "n/a",
                f"{cbd:.8f}" if cbd is not None else "n/a",
                f"{ma10:.6f}" if ma10 is not None else "n/a",
                quote,
                eqs,
            )
        try:
            raw_sig = self.strategy.on_tick(md)
        except Exception as e:  # noqa: BLE001
            logger.exception("on_tick: %s", e)
            await self.mark_error(str(e))
            os._exit(1)
        sig = raw_sig
        amt_override: float | None = None
        if isinstance(raw_sig, dict):
            sig = raw_sig.get("action") or raw_sig.get("signal")
            a = raw_sig.get("amount")
            if a is not None:
                try:
                    amt_override = float(a)
                except (TypeError, ValueError):
                    amt_override = None
        elif isinstance(raw_sig, (tuple, list)) and len(raw_sig) >= 2:
            sig = raw_sig[0]
            try:
                amt_override = float(raw_sig[1])
            except (TypeError, ValueError, IndexError):
                amt_override = None
        if sig in ("BUY", "SELL", "CLOSE_LONG", "CLOSE_SHORT"):
            await self.emit(sig, t, amount_override=amt_override)

    async def emit(self, act: str, t: dict, amount_override: float | None = None) -> None:
        b = self.bot_row or {}
        if amount_override is not None and amount_override > 0:
            amt = float(amount_override)
        else:
            amt = resolve_signal_amount(self.strategy, b.get("params"))
        if amt <= 0:
            logger.warning(
                "signal size missing or 0: set on strategy (signal_amount / order_size / "
                "amount / size or get_signal_amount()) or in bots.params; skip signal"
            )
            return
        sig = {
            "signal_id": str(uuid.uuid4()),
            "bot_id": self.bot_id,
            "version_id": self.bot_id,
            "action": act,
            "type": "MARKET",
            "pair": b.get("trading_pair") or default_trading_pair(),
            "amount": amt,
            "reason": "strategy_on_tick",
            "emitted_at_ms": int(time.time() * 1000),
        }
        self.redis.publish("order_signals", json.dumps(sig))
        self.last_signal_at_ms = int(sig["emitted_at_ms"])
        self.signals += 1
        logger.info(
            "SIGNAL %s %s — hub must consume order_signals; result on %s",
            act,
            sig["signal_id"],
            ORDER_OUTCOMES,
        )
        try:
            logger.info("SIGNAL_PAYLOAD %s", json.dumps(sig, default=str))
        except Exception:  # noqa: BLE001
            logger.info("SIGNAL_PAYLOAD (repr) %r", sig)

    async def mark_error(self, err: str) -> None:
        def _m():
            self.supabase.table("bots").update(
                {
                    "status": "error",
                    "last_error": str(err)[:2000],
                    "last_error_at": _now_iso(),
                }
            ).eq("id", self.bot_id).execute()

        logger.error(
            "WORKER_MARK_BOT_ERROR bot_id=%s — writing bots.status=error to Supabase. reason=%s",
            self.bot_id,
            str(err)[:2000],
        )
        try:
            await asyncio.to_thread(_m)
        except Exception as e:  # noqa: BLE001
            logger.warning("mark_error Supabase update failed: %s", e)

    async def hb_loop(self) -> None:
        inst = os.getenv("RAILWAY_REPLICA_ID", "local")
        ver = (os.getenv("WORKER_VERSION") or os.getenv("RAILWAY_GIT_COMMIT_SHA") or "")[:40]
        while True:
            pl = {
                "bot_id": self.bot_id,
                "worker_instance_id": inst,
                "last_tick_at_ms": self.last_tick_at_ms,
                "last_signal_at_ms": self.last_signal_at_ms,
                "ticks_since_start": self.ticks,
                "signals_since_start": self.signals,
            }
            self.redis.publish("worker:heartbeat", json.dumps(pl))
            lta = _iso_from_ms(self.last_tick_at_ms) or None
            lsa = _iso_from_ms(self.last_signal_at_ms) if self.last_signal_at_ms else None
            row = {
                "bot_id": self.bot_id,
                "last_heartbeat_at": _now_iso(),
                "worker_instance_id": inst,
                "worker_version": ver or None,
                "last_tick_at": lta,
                "last_signal_at": lsa,
            }

            def _u():
                self.supabase.table("bot_heartbeats").upsert(row, on_conflict="bot_id").execute()

            try:
                await asyncio.to_thread(_u)
            except Exception as e:  # noqa: BLE001
                logger.warning("heartbeat upsert: %s", e)
            await asyncio.sleep(15.0)

    async def on_order_outcome(self, raw: str) -> None:
        try:
            d = json.loads(raw)
        except Exception:  # noqa: BLE001
            return
        if str(d.get("bot_id") or "") != str(self.bot_id):
            return
        try:
            full = json.dumps(d, default=str)
        except Exception:  # noqa: BLE001
            full = str(d)
        if len(full) > 4000:
            full = full[:4000] + "…"
        logger.info("HUB_ORDER_OUTCOME_DETAIL %s", full)
        ok = d.get("ok")
        stage = d.get("stage")
        warn_stages = (
            "exchange",
            "balance_check",
            "max_order_size",
            "no_price",
            "bot_not_running",
            "unknown_bot",
            "max_notional",
            "max_open_positions",
            "bad_amount",
            "invalid_amount",
            "empty_pair",
            "exchange_ok_db_fail",
        )
        if ok is False or str(stage or "").lower() in warn_stages:
            logger.warning(
                "HUB_ORDER_OUTCOME_SUMMARY ok=%s stage=%s signal_id=%s message=%s",
                ok,
                stage,
                d.get("signal_id"),
                str(d.get("message", ""))[:800],
            )
        strat = self.strategy
        if strat is None:
            return
        for name in ("on_order_outcome", "on_hub_order_result"):
            fn = getattr(strat, name, None)
            if callable(fn):
                try:
                    fn(d)
                except Exception as e:  # noqa: BLE001
                    logger.exception("%s failed: %s", name, e)
                break

    async def outcomes_loop(self) -> None:
        if self._q_outcomes is None:
            self._q_outcomes = asyncio.Queue(maxsize=500)
        loop = asyncio.get_running_loop()
        threading.Thread(
            target=self._order_outcomes_thread,
            args=(loop,),
            daemon=True,
            name="redis-order-outcomes",
        ).start()
        while True:
            raw = await self._q_outcomes.get()
            await self.on_order_outcome(raw)

    async def hub_stat_loop(self) -> None:
        if self._q_status is None:
            self._q_status = asyncio.Queue()
        l = asyncio.get_running_loop()
        threading.Thread(
            target=self._hub_status_thread, args=(l,), daemon=True
        ).start()
        while True:
            raw = await self._q_status.get()
            try:
                o = json.loads(raw)
                new_status = o.get("status", "healthy")
                prev_h = self.hub_status
                if new_status != prev_h:
                    logger.info(
                        "hub:status %s → %s reason=%s published_at_ms=%s",
                        prev_h,
                        new_status,
                        o.get("reason", ""),
                        o.get("published_at_ms"),
                    )
                    try:
                        logger.info("hub:status_payload %s", json.dumps(o, default=str)[:800])
                    except Exception:  # noqa: BLE001
                        pass
                self.hub_status = new_status
            except Exception:  # noqa: BLE001
                pass

    async def market(self, pair: str) -> None:
        self._q = asyncio.Queue(maxsize=200)
        loop = asyncio.get_running_loop()
        threading.Thread(
            target=self._sub_thread, args=(loop, pair), daemon=True
        ).start()
        while True:
            r = await self._q.get()
            await self.on_tick(r)
            st = (self.bot_row or {}).get("status")
            if (st or "").lower() == "error":
                return

    async def run(self) -> None:
        await self.reload()
        if not self.bot_row:
            raise RuntimeError("no bot")
        if has_bybit_api_credentials():
            logger.info(
                "Worker: Bybit keys found — [feed] will show balance in quote; ohlcv_tf=%s (Bybit kline base vol).",
                self.ohlcv_timeframe,
            )
        else:
            logger.warning(
                "Worker: no Bybit API keys in env — account_equity=n/a. HUB never logs balance; add keys to the worker process.",
            )
        if self.strategy is None:
            msg = self._last_strategy_error or "unknown compile error"
            logger.error(
                "no runnable strategy (%s). Fix bots.content (class Strategy + on_tick, "
                "or def on_tick). Retrying compile every ~5s via config_loop.",
                msg,
            )
        pair = self.bot_row.get("trading_pair") or default_trading_pair()
        await asyncio.gather(
            self.config_loop(),
            self.hb_loop(),
            self.hub_stat_loop(),
            self.outcomes_loop(),
            self.market(pair),
        )


def main() -> None:
    asyncio.run(StrategyWorker().run())


if __name__ == "__main__":
    main()
