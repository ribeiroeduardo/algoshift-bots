# DEPRECATED — use: python -m railway.hub (1 instance) + python -m railway.worker (per BOT_ID).
# See /railway/PHASE_CRITERIA.md. Monolith kept for local experiments only.
import os
import sys
import inspect
import logging
import traceback
import asyncio
import ccxt
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

# Railway/Docker: no TTY → full buffering → deploy log looks empty until process dies
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(line_buffering=True)
    except Exception:
        pass


class _FlushStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    handlers=[_FlushStreamHandler(sys.stderr)],
    force=True,
)
logger = logging.getLogger("RailwayWorker")


def _trace(msg: str) -> None:
    """Always flushed; survives if logging setup fails."""
    print(f"[engine-trace] {msg}", file=sys.stderr, flush=True)


load_dotenv()
# Headless servers: matplotlib defaults may try a GUI backend before strategy code imports it.
os.environ.setdefault("MPLBACKEND", "Agg")
_trace("module loaded, dotenv applied")


def _resolve_env(label: str, *keys: str) -> str:
    for k in keys:
        v = os.getenv(k)
        if v and str(v).strip():
            _trace(f"{label}: using env key {k}")
            return v.strip()
    raise RuntimeError(
        f"missing {label}: set one of {', '.join(keys)} on Railway (Variables tab)"
    )


def _supabase_url() -> str:
    return _resolve_env("Supabase URL", "SUPABASE_URL", "VITE_SUPABASE_URL")


def _supabase_key() -> str:
    return _resolve_env(
        "Supabase key",
        "SUPABASE_KEY",
        "SUPABASE_ANON_KEY",
        "VITE_SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "VITE_SUPABASE_SERVICE_ROLE_KEY",
    )


def _optional_env(label: str, *keys: str) -> str | None:
    for k in keys:
        v = os.getenv(k)
        if v and str(v).strip():
            _trace(f"{label}: using env key {k}")
            return v.strip()
    _trace(f"{label}: none set (tried {', '.join(keys)})")
    return None


class _OnTickFnAdapter:
    """Wraps a module-level ``def on_tick(market_data):`` for the runner."""

    __slots__ = ("_fn",)

    def __init__(self, fn):
        self._fn = fn

    def on_tick(self, market_data):
        return self._fn(market_data)


def _strategy_from_exec_locals(local_context: dict, params: dict) -> tuple[object | None, str | None]:
    """
    Build an object with .on_tick(market_data).
    Accepts: class Strategy, any user class with on_tick, def on_tick, or instance in strategy/bot/runner.
    """
    explicit = os.getenv("STRATEGY_CLASS_NAME", "").strip()
    if explicit and explicit in local_context:
        obj = local_context[explicit]
        if isinstance(obj, type) and callable(getattr(obj, "on_tick", None)):
            _trace(f"_compile_logic: STRATEGY_CLASS_NAME={explicit!r}")
            return obj(params), None
        if not isinstance(obj, type) and callable(getattr(obj, "on_tick", None)):
            _trace(f"_compile_logic: STRATEGY_CLASS_NAME={explicit!r} (instance)")
            return obj, None

    for key in ("strategy", "bot", "runner"):
        obj = local_context.get(key)
        if obj is None or isinstance(obj, type):
            continue
        if callable(getattr(obj, "on_tick", None)):
            _trace(f"_compile_logic: using ready-made instance local[{key!r}]")
            return obj, None

    St = local_context.get("Strategy")
    if isinstance(St, type) and callable(getattr(St, "on_tick", None)):
        return St(params), None

    fn = local_context.get("on_tick")
    if fn is not None and callable(fn) and not isinstance(fn, type):
        if inspect.isroutine(fn) or inspect.isfunction(fn):
            _trace("_compile_logic: using top-level on_tick function (wrapped)")
            return _OnTickFnAdapter(fn), None

    bad_mod = (
        "matplotlib",
        "numpy",
        "pandas",
        "PIL",
        "sklearn",
        "scipy",
        "typing",
        "collections.",
        "ccxt",
        "supabase",
    )
    candidates: list[tuple[str, type]] = []
    for name, obj in local_context.items():
        if name.startswith("_"):
            continue
        if not isinstance(obj, type):
            continue
        if not callable(getattr(obj, "on_tick", None)):
            continue
        mod = getattr(obj, "__module__", "") or ""
        if any(mod.startswith(p) for p in bad_mod):
            continue
        candidates.append((name, obj))

    if len(candidates) == 1:
        name, cls = candidates[0]
        _trace(f"_compile_logic: single candidate class {name!r} (optional: rename to Strategy)")
        return cls(params), None

    for name, cls in candidates:
        if name.lower() == "strategy":
            _trace(f"_compile_logic: using class {name!r}")
            return cls(params), None

    if len(candidates) > 1:
        names = [n for n, _ in candidates]
        return None, f"multiple on_tick classes {names}; set STRATEGY_CLASS_NAME or define class Strategy"

    type_names = sorted(k for k, v in local_context.items() if isinstance(v, type))[:40]
    return None, (
        "need class Strategy with on_tick(self, market_data), or one user class with on_tick, "
        f"or def on_tick(market_data). types_in_locals={type_names}"
    )


class RailwayTradingEngine:
    def __init__(self):
        _trace("RailwayTradingEngine.__init__ start")
        # Conexão Supabase (Railway: no .env file — use Variables; VITE_* matches frontend .env names)
        url = _supabase_url()
        key = _supabase_key()
        _trace("creating supabase client")
        self.supabase: Client = create_client(url, key)
        _trace("supabase client OK")

        # Bybit (CCXT): same VITE_* demo names as local .env
        _trace("creating ccxt bybit")
        bybit_key = _optional_env(
            "Bybit apiKey",
            "BYBIT_API_KEY",
            "VITE_BYBIT_API_KEY",
            "BYBIT_API_KEY_DEMO",
            "VITE_BYBIT_API_KEY_DEMO",
        )
        bybit_secret = _optional_env(
            "Bybit secret",
            "BYBIT_API_SECRET",
            "VITE_BYBIT_API_SECRET",
            "BYBIT_API_SECRET_DEMO",
            "VITE_BYBIT_API_SECRET_DEMO",
        )
        self.exchange = ccxt.bybit(
            {
                "apiKey": bybit_key or "",
                "secret": bybit_secret or "",
                "enableRateLimit": True,
            }
        )
        def _flag(n: str) -> bool:
            return (os.getenv(n) or "").strip().lower() in ("1", "true", "yes")

        use_demo = _flag("BYBIT_USE_DEMO")
        use_testnet = _flag("BYBIT_USE_TESTNET")
        if use_demo and use_testnet:
            raise RuntimeError("set only one: BYBIT_USE_DEMO or BYBIT_USE_TESTNET")
        if use_demo:
            self.exchange.enable_demo_trading(True)
        elif use_testnet:
            self.exchange.set_sandbox_mode(True)
        _trace("ccxt bybit OK")
        
        self.active_version_id = None
        self.strategy_instance = None
        self.is_running = True
        self.start_time = datetime.now()

    async def fetch_and_sync_strategy(self):
        """Load code from public.bots (STRATEGY_ID: latest by version, running)."""
        try:
            _trace("fetch_and_sync: query bots status=running when strategy_id, else by bot id")
            q = self.supabase.table("bots").select("id, strategy_id, version_number, content, status")
            strategy_id = os.getenv("STRATEGY_ID")
            bot_id = os.getenv("BOT_ID")
            if bot_id:
                q = q.eq("id", bot_id)
                _trace(f"fetch_and_sync: filter bot_id={bot_id!r}")
            elif strategy_id:
                q = q.eq("strategy_id", strategy_id).eq("status", "running")
                _trace(f"fetch_and_sync: filter strategy_id={strategy_id!r} status=running")
            response = q.order("version_number", desc=True).limit(1).execute()
            n = len(response.data or [])
            _trace(f"fetch_and_sync: rows={n} active_bot_id={self.active_version_id!r}")
            logger.info("Supabase bots query ok rows=%s", n)

            if response.data:
                row = response.data[0]
                if row["id"] != self.active_version_id:
                    logger.info(
                        "Nova versao ativa bot_id=%s strategy_id=%s v=%s",
                        row["id"],
                        row["strategy_id"],
                        row["version_number"],
                    )
                    if self._compile_logic(row.get("content") or "", {}):
                        self.active_version_id = row["id"]
                else:
                    _trace("fetch_and_sync: same bot id, skip compile")
            else:
                logger.warning(
                    "Nenhum bot (running para STRATEGY_ID, ou BOT_ID) — ver env STRATEGY_ID / BOT_ID: %s / %s",
                    bool(strategy_id),
                    bool(bot_id),
                )
                _trace("fetch_and_sync: empty")
        except Exception as e:
            logger.error(f"Erro ao sincronizar com Supabase: {e}")
            _trace(f"fetch_and_sync EXC: {e!r}")
            traceback.print_exc()

    def _compile_logic(self, code_str, params) -> bool:
        """Run injected code; return True if a runnable .on_tick exists."""
        try:
            code_len = len(code_str or "")
            _trace(f"_compile_logic: code_len={code_len} params_type={type(params).__name__}")
            local_context = {}
            # Same dict for globals+locals so class methods see module-level constants.
            exec(code_str, local_context)
            keys = list(local_context.keys())
            _trace(f"_compile_logic: exec done local_keys={keys[:20]}{'...' if len(keys) > 20 else ''}")

            inst, err = _strategy_from_exec_locals(local_context, params)
            if inst is not None:
                self.strategy_instance = inst
                logger.info("✅ Estratégia pronta (instância com on_tick).")
                _trace("_compile_logic: instance OK")
                return True
            logger.error("❌ %s", err or "no strategy entry")
            _trace(f"_compile_logic: {err or 'no strategy entry'}")
            return False
        except Exception as e:
            logger.error(f"Falha na compilação dinâmica: {e}")
            _trace(f"_compile_logic EXC: {e!r}")
            traceback.print_exc()
            return False

    async def run_loop(self):
        _trace("run_loop: entered")
        logger.info("🚀 Motor iniciado. Monitorando Bybit...")
        
        # Limite de 1 hora de execução (Conforme seu requisito)
        run_duration_seconds = 3600 
        
        while self.is_running:
            # Verifica se o tempo de 1h expirou
            elapsed = (datetime.now() - self.start_time).total_seconds()
            if elapsed > run_duration_seconds:
                logger.info("⏰ Janela de 1h encerrada. Desligando bot.")
                break

            # 1. Sincroniza lógica com banco (pode ser a cada loop ou a cada X minutos)
            await self.fetch_and_sync_strategy()

            if self.strategy_instance:
                try:
                    # 2. Busca dados reais da Bybit
                    # Exemplo: BTC/USDT
                    ticker = self.exchange.fetch_ticker('BTC/USDT')
                    market_data = {
                        'price': ticker['last'],
                        'bid': ticker['bid'],
                        'ask': ticker['ask'],
                        'timestamp': datetime.now()
                    }

                    # 3. Executa lógica da estratégia injetada
                    signal = self.strategy_instance.on_tick(market_data)

                    if signal in ["BUY", "SELL"]:
                        logger.info(f"⚡ SINAL: {signal} a {market_data['price']}")
                        # Aqui você executaria a ordem real:
                        # self.exchange.create_market_order('BTC/USDT', signal.lower(), amount)
                        
                        # 4. Salva o trade no Supabase para seu Frontend ver
                        self._log_trade_to_supabase(signal, market_data['price'])

                except Exception as e:
                    logger.error(f"Erro no loop de trading: {e}")

            await asyncio.sleep(10) # Aguarda 10 segundos para o próximo tick

    def _log_trade_to_supabase(self, side, price):
        """Registra a execução para o seu Dashboard mostrar."""
        try:
            self.supabase.table("trades").insert({
                "bot_id": os.getenv("BOT_ID"),
                "versao_id": self.active_version_id,
                "par_negociacao": "BTC/USDT",
                "direcao": "LONG" if side == "BUY" else "SHORT",
                "preco_entrada": price,
                "resultado": "OPEN"
            }).execute()
        except Exception as e:
            logger.error(f"Erro ao salvar trade: {e}")

if __name__ == "__main__":
    _trace("__main__: start")
    try:
        engine = RailwayTradingEngine()
        _trace("__main__: engine constructed, asyncio.run")
        asyncio.run(engine.run_loop())
        _trace("__main__: asyncio.run finished")
    except Exception as e:
        _trace(f"__main__ FATAL: {e!r}")
        traceback.print_exc()
        raise