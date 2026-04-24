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

# Reconexão das threads Redis: espera inicial, máximo, e fator de backoff
_REDIS_RECONNECT_INIT_S  = 1.0
_REDIS_RECONNECT_MAX_S   = 30.0
_REDIS_RECONNECT_FACTOR  = 2.0


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


def _redis_subscribe_loop(
    channel: str,
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    stop_flag: threading.Event,
    thread_name: str,
) -> None:
    """
    Loop de subscrição Redis com reconexão automática.
    Roda em thread daemon. Reconecta com backoff exponencial em qualquer falha.
    Para quando stop_flag é setado.
    """
    backoff = _REDIS_RECONNECT_INIT_S
    attempt = 0

    while not stop_flag.is_set():
        attempt += 1
        try:
            logger.info("[redis] %s conectando (tentativa %d) canal=%s", thread_name, attempt, channel)
            r = make_redis_client()
            ps = r.pubsub(ignore_subscribe_messages=True)
            ps.subscribe(channel)
            logger.info("[redis] %s subscrito em %s", thread_name, channel)
            backoff = _REDIS_RECONNECT_INIT_S  # reset após conexão bem-sucedida
            attempt = 0

            for msg in ps.listen():
                if stop_flag.is_set():
                    break
                if msg and msg.get("type") == "message" and msg.get("data"):
                    try:
                        loop.call_soon_threadsafe(queue.put_nowait, msg["data"])
                    except asyncio.QueueFull:
                        logger.warning("[redis] %s fila cheia, tick descartado", thread_name)

        except Exception as e:  # noqa: BLE001
            if stop_flag.is_set():
                break
            logger.warning(
                "[redis] %s desconectado: %s — reconectando em %.1fs",
                thread_name, e, backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * _REDIS_RECONNECT_FACTOR, _REDIS_RECONNECT_MAX_S)

    logger.info("[redis] %s thread encerrada", thread_name)


class StrategyWorker:
    def __init__(self) -> None:
        self.bot_id = (os.getenv("BOT_ID") or "").strip()
        if not self.bot_id:
            raise RuntimeError(
                "BOT_ID missing: export BOT_ID=<uuid from public.bots.id>"
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
        self.hub_status = "healthy"
        self._q: asyncio.Queue | None = None
        self._q_status: asyncio.Queue | None = None
        self._last_strategy_error: str | None = None
        self._last_feed_log_m: float = 0.0
        self.ohlcv_timeframe = "15m"
        self._ohlcv_hint: str | None = None
        self._warned_no_bybit: bool = False

        # Flags de controle para threads Redis
        self._stop_market_thread  = threading.Event()
        self._stop_status_thread  = threading.Event()

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
                "bot %s -> error: Set to stopped or running in UI, then restart worker.",
                self.bot_id,
            )
            os._exit(0)

    async def config_loop(self) -> None:
        while True:
            try:
                prev = self.bot_row.get("status") if self.bot_row else None
                await self.reload()
                cur = self.bot_row.get("status") if self.bot_row else None
                if prev and cur and prev != cur:
                    logger.info("status %s -> %s", prev, cur)
            except Exception as e:  # noqa: BLE001
                logger.exception("reload: %s", e)
            await asyncio.sleep(5.0)

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
            return
        st = (self.bot_row or {}).get("status")
        if st != "running":
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
            ohlc = (
                await asyncio.to_thread(get_candle_volume_snapshot, ccxt_pair, self.ohlcv_timeframe)
                if ccxt_pair
                else {
                    "candle_ohlcv_timeframe": self.ohlcv_timeframe,
                    "candle_ohlcv_error": f"no CCXT symbol for trading_pair={pair!r} market_type={mt!r}",
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("ohlcv snapshot: %s", e)
            ohlc = {"candle_ohlcv_error": str(e)}

        if not has_bybit_api_credentials() and not self._warned_no_bybit:
            self._warned_no_bybit = True
            logger.warning(
                "No BYBIT_API_KEY / BYBIT_API_SECRET in this process: account_equity=n/a. "
                "Set the same Bybit (demo) keys on the *worker* process to log balance."
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
            cbf  = ohlc.get("candle_base_volume")
            cbd  = ohlc.get("candle_base_volume_delta")
            ma10 = ohlc.get("candle_closed_vol_ma_10")
            t_open = ohlc.get("candle_open_time_ms")
            base_sym = base_symbol_for_logs(pair or default_trading_pair())
            err = ohlc.get("candle_ohlcv_error")
            if err and self.ticks < 3:
                logger.warning("[ohlcv] %s", err)
            logger.info(
                "[feed] %s price=%s ohlcv_tf=%s t_open=%s %s_forms_cum=%s dV_on_fetch=%s "
                "closed10_MA=%s balance_%s=%s",
                pair, md.get("price"), self.ohlcv_timeframe, t_open, base_sym,
                f"{cbf:.6f}" if cbf is not None else "n/a",
                f"{cbd:.8f}" if cbd is not None else "n/a",
                f"{ma10:.6f}" if ma10 is not None else "n/a",
                quote, eqs,
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
                "signal size 0: set signal_amount / order_size / amount on strategy "
                "or get_signal_amount(), or in bots.params"
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
        logger.info("SIGNAL %s %s", act, sig["signal_id"])

    async def mark_error(self, err: str) -> None:
        def _m():
            self.supabase.table("bots").update(
                {
                    "status": "error",
                    "last_error": str(err)[:2000],
                    "last_error_at": _now_iso(),
                }
            ).eq("id", self.bot_id).execute()

        try:
            await asyncio.to_thread(_m)
        except Exception as e:  # noqa: BLE001
            logger.warning("mark_error: %s", e)

    async def hb_loop(self) -> None:
        inst = os.getenv("RAILWAY_REPLICA_ID", "local")
        ver  = (os.getenv("WORKER_VERSION") or os.getenv("RAILWAY_GIT_COMMIT_SHA") or "")[:40]
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

    async def hub_stat_loop(self) -> None:
        """Consome hub:status via fila preenchida pela thread com reconexão."""
        if self._q_status is None:
            self._q_status = asyncio.Queue(maxsize=50)
        loop = asyncio.get_running_loop()
        threading.Thread(
            target=_redis_subscribe_loop,
            args=("hub:status", self._q_status, loop, self._stop_status_thread, "hub-status"),
            daemon=True,
            name="redis-hub-status",
        ).start()
        while True:
            raw = await self._q_status.get()
            try:
                o = json.loads(raw)
                new_status = o.get("status", "healthy")
                if new_status != self.hub_status:
                    logger.info("hub:status %s → %s", self.hub_status, new_status)
                self.hub_status = new_status
            except Exception:  # noqa: BLE001
                pass

    async def market(self, pair: str) -> None:
        self._q = asyncio.Queue(maxsize=200)
        loop = asyncio.get_running_loop()
        threading.Thread(
            target=_redis_subscribe_loop,
            args=(f"market_data:{pair}", self._q, loop, self._stop_market_thread, f"market-{pair}"),
            daemon=True,
            name=f"redis-market-{pair}",
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
                "Worker: Bybit keys found — balance in quote active; ohlcv_tf=%s",
                self.ohlcv_timeframe,
            )
        else:
            logger.warning(
                "Worker: no Bybit API keys — account_equity=n/a. "
                "Add BYBIT_API_KEY + BYBIT_API_SECRET to the worker service."
            )
        if self.strategy is None:
            msg = self._last_strategy_error or "unknown compile error"
            logger.error(
                "no runnable strategy (%s). Fix bots.content. Retrying via config_loop.", msg
            )
        pair = self.bot_row.get("trading_pair") or default_trading_pair()
        try:
            await asyncio.gather(
                self.config_loop(),
                self.hb_loop(),
                self.hub_stat_loop(),
                self.market(pair),
            )
        finally:
            # Sinaliza threads para parar na saída limpa
            self._stop_market_thread.set()
            self._stop_status_thread.set()


def main() -> None:
    asyncio.run(StrategyWorker().run())


if __name__ == "__main__":
    main()