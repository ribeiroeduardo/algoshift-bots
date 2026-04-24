import os
import sys
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
_trace("module loaded, dotenv applied")


def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"missing env: {name}")
    return v


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


class RailwayTradingEngine:
    def __init__(self):
        _trace("RailwayTradingEngine.__init__ start")
        # Conexão Supabase (Railway: no .env file — use Variables; VITE_* matches frontend .env names)
        url = _supabase_url()
        key = _supabase_key()
        _trace("creating supabase client")
        self.supabase: Client = create_client(url, key)
        _trace("supabase client OK")

        # Conexão Bybit (via CCXT)
        _trace("creating ccxt bybit")
        self.exchange = ccxt.bybit({
            "apiKey": os.getenv("BYBIT_API_KEY"),
            "secret": os.getenv("BYBIT_API_SECRET"),
            "enableRateLimit": True,
        })
        _trace("ccxt bybit OK")
        
        self.active_version_id = None
        self.strategy_instance = None
        self.is_running = True
        self.start_time = datetime.now()

    async def fetch_and_sync_strategy(self):
        """Load active row from public.strategy_versions (status enum: active)."""
        try:
            # Schema: strategy_versions(id, strategy_id, version_number, content, status, ...)
            # Optional STRATEGY_ID env scopes to one strategy; else newest active by version_number.
            _trace("fetch_and_sync: query strategy_versions status=active")
            q = (
                self.supabase.table("strategy_versions")
                .select("id, strategy_id, version_number, content, status")
                .eq("status", "active")
            )
            strategy_id = os.getenv("STRATEGY_ID")
            if strategy_id:
                q = q.eq("strategy_id", strategy_id)
                _trace(f"fetch_and_sync: filter strategy_id={strategy_id!r}")
            response = q.order("version_number", desc=True).limit(1).execute()
            n = len(response.data or [])
            _trace(f"fetch_and_sync: rows={n} active_version_id={self.active_version_id!r}")
            logger.info("Supabase strategy_versions query ok rows=%s", n)

            if response.data:
                version = response.data[0]
                if version["id"] != self.active_version_id:
                    logger.info(
                        "Nova versao ativa id=%s strategy_id=%s v=%s",
                        version["id"],
                        version["strategy_id"],
                        version["version_number"],
                    )
                    self.active_version_id = version["id"]
                    # No per-version params column in schema; strategies use empty dict unless extended.
                    self._compile_logic(version["content"], {})
                else:
                    _trace("fetch_and_sync: same version id, skip compile")
            else:
                logger.warning(
                    "Nenhuma strategy_versions com status=active (STRATEGY_ID set? %s)",
                    bool(strategy_id),
                )
                _trace(
                    "fetch_and_sync: empty (table strategy_versions, status active; optional env STRATEGY_ID)"
                )
        except Exception as e:
            logger.error(f"Erro ao sincronizar com Supabase: {e}")
            _trace(f"fetch_and_sync EXC: {e!r}")
            traceback.print_exc()

    def _compile_logic(self, code_str, params):
        """Injeta dinamicamente o código Python (Opção A)."""
        try:
            code_len = len(code_str or "")
            _trace(f"_compile_logic: code_len={code_len} params_type={type(params).__name__}")
            local_context = {}
            # Executa a string de código no contexto local
            exec(code_str, {}, local_context)
            keys = list(local_context.keys())
            _trace(f"_compile_logic: exec done local_keys={keys[:20]}{'...' if len(keys) > 20 else ''}")

            if "Strategy" in local_context:
                # Instancia a classe passando os parâmetros do banco
                self.strategy_instance = local_context["Strategy"](params)
                logger.info("✅ Estratégia instanciada com sucesso.")
                _trace("_compile_logic: Strategy() OK")
            else:
                logger.error("❌ Classe 'Strategy' não encontrada no código injetado.")
                _trace("_compile_logic: no Strategy class in local_context")
        except Exception as e:
            logger.error(f"Falha na compilação dinâmica: {e}")
            _trace(f"_compile_logic EXC: {e!r}")
            traceback.print_exc()

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