import os
import time
import logging
import traceback
import asyncio
import ccxt
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

# Configuração de Logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger("RailwayWorker")

load_dotenv()

class RailwayTradingEngine:
    def __init__(self):
        # Conexão Supabase
        self.supabase: Client = create_client(
            os.getenv("SUPABASE_URL"), 
            os.getenv("SUPABASE_KEY")
        )
        
        # Conexão Bybit (via CCXT)
        self.exchange = ccxt.bybit({
            'apiKey': os.getenv("BYBIT_API_KEY"),
            'secret': os.getenv("BYBIT_API_SECRET"),
            'enableRateLimit': True,
        })
        
        self.active_version_id = None
        self.strategy_instance = None
        self.is_running = True
        self.start_time = datetime.now()

    async def fetch_and_sync_strategy(self):
        """Busca a versão ativa no Supabase e compila se houver mudança."""
        try:
            # Query buscando a versão marcada como e_ativa=true
            response = self.supabase.table("versoes") \
                .select("id, codigo_python, parametros") \
                .eq("e_ativa", True) \
                .limit(1).execute()

            if response.data:
                version = response.data[0]
                if version['id'] != self.active_version_id:
                    logger.info(f"🔄 Nova versão detectada (ID: {version['id']}). Atualizando lógica...")
                    self.active_version_id = version['id']
                    self._compile_logic(version['codigo_python'], version['parametros'])
            else:
                logger.warning("⚠️ Nenhuma versão ativa encontrada no Supabase.")
        except Exception as e:
            logger.error(f"Erro ao sincronizar com Supabase: {e}")

    def _compile_logic(self, code_str, params):
        """Injeta dinamicamente o código Python (Opção A)."""
        try:
            local_context = {}
            # Executa a string de código no contexto local
            exec(code_str, {}, local_context)
            
            if 'Strategy' in local_context:
                # Instancia a classe passando os parâmetros do banco
                self.strategy_instance = local_context['Strategy'](params)
                logger.info("✅ Estratégia instanciada com sucesso.")
            else:
                logger.error("❌ Classe 'Strategy' não encontrada no código injetado.")
        except Exception as e:
            logger.error(f"Falha na compilação dinâmica: {e}")
            traceback.print_exc()

    async def run_loop(self):
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
    engine = RailwayTradingEngine()
    asyncio.run(engine.run_loop())