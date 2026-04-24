"""
ESTRATÉGIA: OPENING RANGE BREAKOUT (ORB) MULTI-TIMEFRAME (ADAPTATIVA + CONFIRMAÇÃO)
-------------------------------------------------------
Esta estratégia opera o rompimento dos primeiros minutos de negociação do mercado.

PASSO A PASSO DA ESTRATÉGIA:
1. DEFINIÇÃO DO RANGE: O robô monitora o preço entre 09:30 e 10:00 (horário de NY) 
   para identificar a Máxima e a Mínima deste período (o 'Range').
2. FILTROS DE VOLATILIDADE (ATR): O dia é ignorado se o Range for menor que uma 
   proporção do ATR (Average True Range), evitando mercados "mortos".
3. GATILHO (SIGNAL_TF): O rompimento é identificado em um timeframe maior (ex: 15min).
   Pode ser por FECHAMENTO do candle fora do range, ou simples TOQUE.
4. CONFIRMAÇÃO DE SINAL: Se USE_CONFIRMATION_BREAK for True, o robô aguarda o preço 
   superar a Máxima/Mínima do candle de sinal para entrar.
5. PREÇO DE ENTRADA: Independentemente da confirmação, o preço de entrada SEMPRE 
   será o topo ou fundo do range (conforme configurado em ENTRY_PRICE_TYPE).
6. DIMENSIONAMENTO DE RISCO: A quantidade é calculada para que a perda no Stop 
   seja de exatamente X% do patrimônio, respeitando o teto de alavancagem.
7. GESTÃO DE SAÍDA (BASE_TF): Monitoramento para TP, SL, Break-Even ou Tempo.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import os

# ==============================================================================
# 1. CONFIGURAÇÕES E PARÂMETROS (PAINEL DE CONTROLE)
# ==============================================================================
CSV_FILE_PATH = '/Users/eduardoribeiro/Library/CloudStorage/GoogleDrive-edunius@gmail.com/Meu Drive/backtesting/csv/BTCUSDT_1m_REAL.csv'

# --- CONFIGURAÇÃO DE TEMPO (TIMEFRAMES) ---
BASE_TF   = '15min'   # Timeframe para gestão (Stop/Alvo/Saída)
SIGNAL_TF = '15min'  # Timeframe para sinal (ATR/Confirmação de Rompimento)

# --- GESTÃO DE CAPITAL E RISCO DINÂMICO ---
INITIAL_CAPITAL    = 10000.0  
RISK_PER_TRADE_PCT = 1.0       
MAX_LEVERAGE       = 1.0      

# ==============================================================================
# HORÁRIOS DOS MERCADOS (Base: Fuso de Nova York 'America/New_York')
# ------------------------------------------------------------------------------
# Escolha a abertura que deseja operar definindo o START_RANGE:
# - Abertura de LONDRES : '03:00' (08:00 no horário local de Londres)
# - Abertura de NOVA YORK : '09:30' (Para ações, ou 08:00 para crypto/forex NY)
# - Abertura de TÓQUIO : '20:00' (09:00 do dia seguinte no horário de Tóquio)
# ==============================================================================
START_RANGE         = '09:30'
RANGE_MINUTES       = 15         # ESCOLHA O RANGE: 15 (ex: até 09:45) ou 30 (ex: até 10:00)
END_OF_DAY          = '23:59'

# ESCOLHA OS DIAS DE OPERAÇÃO:
# Opções válidas: 'ALL' (Todos), 'WEEKDAYS' (Seg-Sex), 'WEEKENDS' (Sáb-Dom), 'SATURDAY' (Sáb), 'SUNDAY' (Dom)
TRADE_DAYS          = 'WEEKDAYS'

# Parâmetros da Estratégia
RISK_REWARD      = 3.0      
STOP_TYPE        = 'OPPOSITE' 
ENTRY_BUFFER_PCT = 0.02      

# --- CONFIGURAÇÃO DE ENTRADA ---
# ENTRY_TYPE: 'CLOSING' (O candle de sinal deve FECHAR fora do range)
#             'TOUCH'   (Basta a máxima/mínima do candle de sinal TOCAR fora do range)
ENTRY_TYPE = 'CLOSING' 

# Nível de Preço para Entrada: 'RANGE_EXTREME' ou 'PREV_CANDLE'
ENTRY_PRICE_TYPE = 'RANGE_EXTREME' 

# --- CONFIRMAÇÃO DE ROMPIMENTO (OPCIONAL) ---
# Se TRUE, a perda da máxima/mínima do candle de sinal é apenas o gatilho,
# mas a entrada continua sendo no preço definido em ENTRY_PRICE_TYPE.
USE_CONFIRMATION_BREAK = True 

# --- FILTRO DE VOLATILIDADE DINÂMICA (ATR) ---
USE_ATR_FILTER      = True  
ATR_PERIOD          = 14    
MIN_RANGE_ATR_MULT  = 1.0   
USE_MAX_RANGE_FILTER = True  
MAX_RANGE_PT         = 2000  

# --- FILTROS DE VOLUME ---
USE_VOLUME_FILTER   = True
VOLUME_MA_PERIOD    = 10    
VOLUME_MULTIPLIER   = 2.0  

# --- GESTÃO DE PROTEÇÃO (BREAK-EVEN) ---
USE_BREAK_EVEN      = True  
BE_TRIGGER_RR       = 1.0   

# --- CONTROLE DE DURACAO ---
MAX_TRADE_DURATION  = 30    

# --- CUSTOS OPERACIONAIS ---
COMMISSION_RATE = 0.0002 
# SLIPPAGE_BPS: Otimista (1.0), Realista (3.0-5.0), Conservador (10.0)
SLIPPAGE_BPS    = 3.0 / 10000 

# --- NOVO: GERAR RESULTADOS PARA VÁRIOS PERÍODOS ---
GENERATE_MULTI_PERIOD_REPORT = True

# ==============================================================================
# 2. CARREGAMENTO E TRATAMENTO DE DADOS
# ==============================================================================
def load_and_resample(path, tf_base, tf_signal):
    if not os.path.exists(path):
        print(f"\n[ERRO] O ficheiro '{path}' não foi encontrado.")
        return None, None, None, None, None
    
    print(f"\n[1/3] Lendo e higienizando dados...")
    with open(path, 'r') as f:
        first_line = f.readline()
        sep = ';' if ';' in first_line else ','

    try:
        df_1m = pd.read_csv(path, sep=sep, low_memory=False)
        df_1m.columns = [c.lower().strip() for c in df_1m.columns]
        essential = ['open', 'high', 'low', 'close', 'volume']
        for col in essential:
            df_1m[col] = pd.to_numeric(df_1m[col].astype(str).str.replace(',', ''), errors='coerce')
        
        df_1m.dropna(subset=essential, inplace=True)
        # Filtro contra lixo de turnover no preço
        valid = (df_1m['high'] <= df_1m['open'] * 1.2) & (df_1m['low'] >= df_1m['open'] * 0.8)
        df_1m = df_1m[valid]
            
    except Exception as e:
        print(f"[ERRO] Falha no CSV: {e}")
        return None, None, None, None, None
    
    time_col = next((c for c in ['timestamp', 'time', 'date', 'open time', 'datetime'] if c in df_1m.columns), df_1m.columns[0])
    unit = 'ms' if df_1m[time_col].iloc[0] > 1e11 else 's'
    df_1m[time_col] = pd.to_datetime(df_1m[time_col], unit=unit)
    df_1m.set_index(time_col, inplace=True)
    df_1m.sort_index(inplace=True)
    
    if df_1m.index.tz is None: 
        df_1m.index = df_1m.index.tz_localize('UTC')
    df_1m.index = df_1m.index.tz_convert('America/New_York')

    start_p, end_p = df_1m['close'].iloc[0], df_1m['close'].iloc[-1]
    total_min = (df_1m.index[-1] - df_1m.index[0]).total_seconds() / 60

    def resample_df(df, tf):
        return df.resample(tf).agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()

    df_base = resample_df(df_1m, tf_base)
    df_signal = resample_df(df_1m, tf_signal)
    
    high, low, prev_close = df_signal['high'], df_signal['low'], df_signal['close'].shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df_signal['atr'] = tr.rolling(window=ATR_PERIOD).mean()
    df_signal['vol_ma'] = df_signal['volume'].rolling(window=VOLUME_MA_PERIOD).mean()
    df_base['vol_ma'] = df_base['volume'].rolling(window=VOLUME_MA_PERIOD).mean() # Nova MA pro TF de 5m
    
    return df_base, df_signal, start_p, end_p, total_min

# ==============================================================================
# 3. MOTOR DE BACKTEST MULTI-TIMEFRAME
# ==============================================================================
def run_backtest(df_base, df_signal):
    print(f"[2/3] Executando Backtest MTF...")
    df_base['date_only'] = df_base.index.date
    trades = []
    current_equity = INITIAL_CAPITAL
    
    from datetime import timedelta
    start_dt = datetime.strptime(START_RANGE, '%H:%M')
    end_dt = start_dt + timedelta(minutes=RANGE_MINUTES)
    end_range_str = end_dt.strftime('%H:%M')
    
    for date, daily_base in df_base.groupby('date_only'):
        if current_equity <= 0: break
        
        # Filtro de Dias de Operação (0=Seg, 1=Ter, 2=Qua, 3=Qui, 4=Sex, 5=Sáb, 6=Dom)
        wd = date.weekday()
        if TRADE_DAYS == 'WEEKDAYS' and wd >= 5:
            continue
        elif TRADE_DAYS == 'WEEKENDS' and wd < 5:
            continue
        elif TRADE_DAYS == 'SATURDAY' and wd != 5:
            continue
        elif TRADE_DAYS == 'SUNDAY' and wd != 6:
            continue
        
        try:
            range_data = daily_base.between_time(START_RANGE, end_range_str, inclusive='left')
        except:
            range_data = daily_base.between_time(START_RANGE, end_range_str, include_end=False)
            
        if range_data.empty: continue
        r_high, r_low = range_data['high'].max(), range_data['low'].min()
        r_size = r_high - r_low
        
        if USE_ATR_FILTER:
            daily_sig = df_signal[df_signal.index.date == date]
            if daily_sig.empty: continue
            try:
                current_atr = daily_sig.between_time(START_RANGE, end_range_str).iloc[-1]['atr']
            except IndexError:
                continue
            if r_size < (current_atr * MIN_RANGE_ATR_MULT): continue
            
        if USE_MAX_RANGE_FILTER and r_size > MAX_RANGE_PT: continue

        # Agora o robô busca o sinal e executa TUDO diretamente no timeframe de 5m
        try:
            exc_win = daily_base.between_time(end_range_str, END_OF_DAY, inclusive='both')
        except:
            exc_win = daily_base.between_time(end_range_str, END_OF_DAY)

        pos_type, entry_time = None, None
        in_trade = False
        qty, is_be_active = 0, False
        trigger_level, entry_price_final, sl, tp = None, None, None, None

        for e_idx, e_row in exc_win.iterrows():
            if pos_type is None:
                # FASE 1: PROCURA O SINAL DE ROMPIMENTO NO CANDLE DE 5M
                l_trig, s_trig = r_high * (1 + (ENTRY_BUFFER_PCT/100)), r_low * (1 - (ENTRY_BUFFER_PCT/100))
                vol_ok = e_row['volume'] >= (e_row['vol_ma'] * VOLUME_MULTIPLIER) if USE_VOLUME_FILTER else True

                is_trig_signal = False
                if vol_ok:
                    if ENTRY_TYPE == 'CLOSING':
                        if e_row['close'] > l_trig: pos_type, is_trig_signal = 'LONG', True
                        elif e_row['close'] < s_trig: pos_type, is_trig_signal = 'SHORT', True
                    else: # TOUCH
                        if e_row['high'] >= l_trig: pos_type, is_trig_signal = 'LONG', True
                        elif e_row['low'] <= s_trig: pos_type, is_trig_signal = 'SHORT', True

                if is_trig_signal:
                    if ENTRY_PRICE_TYPE == 'PREV_CANDLE':
                        loc = daily_base.index.get_loc(e_idx)
                        prev = daily_base.iloc[loc - 1]
                        entry_price_final = prev['high'] if pos_type == 'LONG' else prev['low']
                    else:
                        entry_price_final = l_trig if pos_type == 'LONG' else s_trig
                    
                    if USE_CONFIRMATION_BREAK:
                        trigger_level = e_row['high'] if pos_type == 'LONG' else e_row['low']
                    else:
                        trigger_level = entry_price_final
                continue # Pula para o próximo candle (impede entrada cega no mesmo minuto do sinal)
                
            if pos_type is not None and not in_trade:
                # FASE 2: GATILHO DE ENTRADA ATIVADO PELA CONFIRMAÇÃO
                if (pos_type == 'LONG' and e_row['high'] >= trigger_level) or \
                   (pos_type == 'SHORT' and e_row['low'] <= trigger_level):
                    
                    in_trade = True
                    entry_time = e_idx
                    
                    sl = (r_low if STOP_TYPE == 'OPPOSITE' else (r_low + r_size/2)) if pos_type == 'LONG' else (r_high if STOP_TYPE == 'OPPOSITE' else (r_low + r_size/2))
                    dist = abs(entry_price_final - sl)
                    if dist == 0: dist = 1e-5
                    tp = entry_price_final + (dist * RISK_REWARD) if pos_type == 'LONG' else entry_price_final - (dist * RISK_REWARD)
                    
                    qty = (current_equity * (RISK_PER_TRADE_PCT / 100.0)) / dist
                    leverage = (qty * entry_price_final) / current_equity
                    if leverage > MAX_LEVERAGE:
                        qty = (current_equity * MAX_LEVERAGE) / entry_price_final
                        leverage = MAX_LEVERAGE
                continue # Deixa a avaliação do trade para o candle seguinte para ser realista
                
            if in_trade:
                # FASE 3: GESTÃO DO TRADE NO TIMEFRAME DE 5M
                exit_p, res = None, None
                if pos_type == 'LONG':
                    if e_row['low'] <= sl: exit_p, res = sl, 'LOSS'
                    elif e_row['high'] >= tp: exit_p, res = tp, 'WIN'
                else:
                    if e_row['high'] >= sl: exit_p, res = sl, 'LOSS'
                    elif e_row['low'] <= tp: exit_p, res = tp, 'WIN'

                if exit_p is None and USE_BREAK_EVEN and not is_be_active:
                    dist_be = abs(entry_price_final - sl)
                    if (pos_type == 'LONG' and e_row['high'] >= entry_price_final + (dist_be * BE_TRIGGER_RR)) or \
                       (pos_type == 'SHORT' and e_row['low'] <= entry_price_final - (dist_be * BE_TRIGGER_RR)):
                        sl, is_be_active = entry_price_final, True

                if exit_p is None and MAX_TRADE_DURATION > 0:
                    if ((e_idx - entry_time).total_seconds() / 60.0) >= MAX_TRADE_DURATION: exit_p, res = e_row['close'], 'DURATION_EXIT'
                if exit_p is None and e_idx.time() >= datetime.strptime(END_OF_DAY, "%H:%M").time(): exit_p, res = e_row['close'], 'TIME_EXIT'

                if exit_p:
                    c_v = (entry_price_final + exit_p) * COMMISSION_RATE * qty
                    s_v = (entry_price_final + exit_p) * SLIPPAGE_BPS * qty
                    gross = (exit_p - entry_price_final) * qty if pos_type == 'LONG' else (entry_price_final - exit_p) * qty
                    net_trade = gross - c_v - s_v
                    current_equity += net_trade
                    trades.append({
                        'datetime': e_idx, 'type': pos_type, 'result': res, 'gross_pnl': gross, 
                        'net_pnl': net_trade, 'comm': c_v, 'slip': s_v, 'entry_p': entry_price_final, 
                        'exit_p': exit_p, 'sl': sl, 'tp': tp, 'qty': qty, 'lev': leverage, 
                        'equity': current_equity, 'dur': (e_idx - entry_time).total_seconds() / 60.0
                    })
                    break
        
    return pd.DataFrame(trades)

# ==============================================================================
# 4. RELATÓRIOS E GERAÇÃO DE HTML E GRÁFICOS
# ==============================================================================
def plot_recent_trades_candlestick(df_base, results, days=30):
    if results.empty: return
    
    # Filtra apenas os últimos N dias para o gráfico não ficar incompreensível
    end_date = df_base.index.max()
    start_date = end_date - pd.Timedelta(days=days)
    
    df_plot = df_base[df_base.index >= start_date].copy()
    trades_plot = results[results['datetime'] >= start_date]
    
    if df_plot.empty: return
    
    plt.figure(figsize=(15, 7))
    
    # 1. Separando candles de alta e baixa
    up = df_plot[df_plot['close'] >= df_plot['open']]
    down = df_plot[df_plot['close'] < df_plot['open']]
    
    # Largura da barra baseada no timeframe (aprox. p/ 5min)
    width = 0.003
    
    # 2. Desenhando os Pavios (High/Low)
    plt.vlines(df_plot.index, df_plot['low'], df_plot['high'], color='gray', linewidth=0.5, alpha=0.5)
    
    # 3. Desenhando os Corpos (Open/Close)
    plt.bar(up.index, up['close'] - up['open'], bottom=up['open'], color='#2ecc71', width=width, alpha=0.8)
    plt.bar(down.index, down['open'] - down['close'], bottom=down['close'], color='#e74c3c', width=width, alpha=0.8)
    
    # 4. Marcando as entradas e saídas
    longs = trades_plot[trades_plot['type'] == 'LONG']
    shorts = trades_plot[trades_plot['type'] == 'SHORT']
    
    plt.scatter(longs['datetime'], longs['entry_p'], marker='^', color='blue', s=120, label='Compra (Long)', zorder=5)
    plt.scatter(shorts['datetime'], shorts['entry_p'], marker='v', color='purple', s=120, label='Venda (Short)', zorder=5)
    plt.scatter(trades_plot['datetime'], trades_plot['exit_p'], marker='x', color='black', s=60, label='Saída', zorder=5)
    
    plt.title(f"Gráfico de Candles com Trades (Últimos {days} dias)", fontsize=14)
    plt.legend()
    plt.grid(True, alpha=0.2)
    plt.tight_layout()
    plt.savefig('candlestick_trades.png')
    print(f"[OK] 'candlestick_trades.png' gerado com os trades dos últimos {days} dias.")

def generate_trades_html(results):
    if results.empty: return
    def rt(df):
        rows = ""
        for _, r in df.iterrows():
            p_c = "win" if r['net_pnl'] > 0 else "loss"
            rows += f"""<tr><td>{r['datetime'].strftime('%d/%m/%Y %H:%M')}</td><td>{r['type']}</td><td class="val">{r['lev']:.1f}x</td><td class="val">{r['qty']:,.4f}</td><td class="val">${r['entry_p']:,.2f}</td><td class="val" style="color:#e74c3c">${r['sl']:,.2f}</td><td class="val" style="color:#2ecc71">${r['tp']:,.2f}</td><td class="val">${r['exit_p']:,.2f}</td><td class="val">${r['qty']*r['entry_p']:,.2f}</td><td class="val">${r['qty']*r['exit_p']:,.2f}</td><td class="val">${r['comm']:,.2f}</td><td class="val">${r['slip']:,.2f}</td><td class="val">${r['gross_pnl']:,.2f}</td><td class="val {p_c}">${r['net_pnl']:,.2f}</td><td class="val">${r['equity']:,.2f}</td></tr>"""
        return rows
    
    html = f"""<html><head><meta charset='UTF-8'><style>body{{font-family:sans-serif;background:#121212;color:#eee;padding:20px;}}table{{width:100%;border-collapse:collapse;background:#1e1e1e;margin-bottom:40px;font-size:11px;}}th,td{{padding:8px;border-bottom:1px solid #333;text-align:left;white-space:nowrap;}}th{{background:#2c3e50;text-transform:uppercase;}} .win{{color:#2ecc71;font-weight:bold;}} .loss{{color:#e74c3c;font-weight:bold;}} .val{{font-family:monospace;}} h2{{color:#3498db;border-left:4px solid #3498db;padding-left:10px;}}</style></head><body><h2>🚀 Primeiros 5 Trades</h2><table><thead><tr><th>Data</th><th>Tipo</th><th>Alav.</th><th>Qtd</th><th>Entrada</th><th>SL</th><th>Target</th><th>Saída</th><th>Tot. Ent.</th><th>Tot. Saída</th><th>Taxa</th><th>Slip</th><th>Bruto</th><th>Líquido</th><th>Património</th></tr></thead><tbody>{rt(results.head(5))}</tbody></table><h2>📊 Últimos 5 Trades</h2><table><thead><tr><th>Data</th><th>Tipo</th><th>Alav.</th><th>Qtd</th><th>Entrada</th><th>SL</th><th>Target</th><th>Saída</th><th>Tot. Ent.</th><th>Tot. Saída</th><th>Taxa</th><th>Slip</th><th>Bruto</th><th>Líquido</th><th>Património</th></tr></thead><tbody>{rt(results.tail(5))}</tbody></table></body></html>"""
    
    with open('trades_report.html', 'w', encoding='utf-8') as f: 
        f.write(html)
    print("\n[OK] 'trades_report.html' gerado.")

def show_report(results, df_base, start_p, end_p, total_min):
    if results.empty: 
        print("[!] Sem trades.")
        return
        
    net = results['net_pnl'].sum()
    wins = len(results[results['net_pnl'] > 0])
    
    # CORREÇÃO 1: Drawdown agora considera o capital inicial
    equity_series = pd.Series([INITIAL_CAPITAL] + results['equity'].tolist())
    peak = equity_series.cummax()
    max_dd = ((peak - equity_series) / peak).max() * 100
    
    daily_eq = pd.Series(index=pd.Series(df_base.index.date).unique(), dtype=float)
    daily_eq.update(results.groupby(results['datetime'].dt.date)['equity'].last())
    daily_eq = daily_eq.ffill().fillna(INITIAL_CAPITAL)
    daily_rets = daily_eq.pct_change().dropna()
    
    # Sharpe ajustado para dias corridos (ex: Cripto)
    sharpe = (daily_rets.mean() / daily_rets.std()) * np.sqrt(365) if daily_rets.std() > 0 else 0

    # Cálculo da relação de dias com trade / dias totais
    all_dates = pd.Series(df_base.index.date).unique()
    
    if TRADE_DAYS == 'WEEKDAYS':
        total_days = sum(1 for d in all_dates if d.weekday() < 5)
        op_days_str = 'Apenas Dias Úteis (Seg-Sex)'
    elif TRADE_DAYS == 'WEEKENDS':
        total_days = sum(1 for d in all_dates if d.weekday() >= 5)
        op_days_str = 'Apenas Finais de Semana (Sáb-Dom)'
    elif TRADE_DAYS == 'SATURDAY':
        total_days = sum(1 for d in all_dates if d.weekday() == 5)
        op_days_str = 'Apenas Sábados'
    elif TRADE_DAYS == 'SUNDAY':
        total_days = sum(1 for d in all_dates if d.weekday() == 6)
        op_days_str = 'Apenas Domingos'
    else:
        total_days = len(all_dates)
        op_days_str = 'Todos os Dias'
        
    traded_days = results['datetime'].dt.date.nunique()

    print("\n[3/3] RESUMO DOS PARÂMETROS E PERFORMANCE")  
    print("-" * 60)  
    
    gross_total = results['gross_pnl'].sum()
    total_fees = results['comm'].sum() + results['slip'].sum()
    
    gross_profits = results[results['net_pnl'] > 0]['net_pnl'].sum()
    gross_losses = abs(results[results['net_pnl'] < 0]['net_pnl'].sum())
    
    if gross_losses == 0:
        profit_factor_str = "Infinito (Sem perdas)"
    else:
        profit_factor_str = f"{gross_profits / gross_losses:,.2f}"
    
    print(f"Retorno (%): {(net/INITIAL_CAPITAL)*100:,.2f}%")
    print(f"Taxa de Acerto: {(wins/len(results))*100:,.2f}% ({wins}W / {len(results)-wins}L)")
    print(f"Fator de Lucro: {profit_factor_str}")
    print(f"Max Drawdown (%): {max_dd:,.2f}%")
    
    # --- NOVA ESTATÍSTICA: SINAIS POR DIA ---
    if total_days > 0:
        sinais_por_dia = len(results) / total_days
        print(f"Dias Operados: {traded_days} de {total_days} válidos ({(traded_days/total_days)*100:.1f}%)")
        print(f"Sinais por dia: {sinais_por_dia:,.2f}")
    else:
        print(f"Dias Operados: {traded_days} de {total_days} válidos (0.0%)")
        print(f"Sinais por dia: 0.00")
    print("-" * 60)
    
    # --- NOVO BLOCO: RELATÓRIO MULTI-PERÍODO ---
    if GENERATE_MULTI_PERIOD_REPORT:
        print("\n[RELATÓRIO MULTI-PERÍODO]")
        print("-" * 85)
        print(f"{'Período':<15} | {'Retorno (%)':<12} | {'Win Rate':<16} | {'Fator de Lucro':<14} | {'Max DD (%)':<10}")
        print("-" * 85)
        
        end_date = df_base.index.max()
        periods = [
            ('Tudo', None),
            ('Últimos 3M', 3),
            ('Últimos 6M', 6),
            ('Últimos 12M', 12),
            ('Últimos 24M', 24),
            ('Últimos 36M', 36)
        ]
        
        for name, months in periods:
            if months is None:
                res_slice = results
                start_eq = INITIAL_CAPITAL
            else:
                start_date = end_date - pd.DateOffset(months=months)
                res_slice = results[results['datetime'] >= start_date]
                
                if res_slice.empty:
                    print(f"{name:<15} | Sem trades no período")
                    continue
                    
                # Capital inicial deste período (equity do trade anterior ao período, ou inicial)
                past_trades = results[results['datetime'] < start_date]
                start_eq = past_trades['equity'].iloc[-1] if not past_trades.empty else INITIAL_CAPITAL
            
            net_slice = res_slice['net_pnl'].sum()
            wins_slice = len(res_slice[res_slice['net_pnl'] > 0])
            total_slice = len(res_slice)
            win_rate_slice = (wins_slice / total_slice) * 100 if total_slice > 0 else 0
            
            gross_prof_slice = res_slice[res_slice['net_pnl'] > 0]['net_pnl'].sum()
            gross_loss_slice = abs(res_slice[res_slice['net_pnl'] < 0]['net_pnl'].sum())
            pf_slice = gross_prof_slice / gross_loss_slice if gross_loss_slice > 0 else float('inf')
            pf_str_slice = f"{pf_slice:,.2f}" if pf_slice != float('inf') else "Inf"
            
            eq_series_slice = pd.Series([start_eq] + res_slice['equity'].tolist())
            peak_slice = eq_series_slice.cummax()
            dd_slice = ((peak_slice - eq_series_slice) / peak_slice).max() * 100
            ret_slice = (net_slice / start_eq) * 100
            
            print(f"{name:<15} | {ret_slice:>11.2f}% | {win_rate_slice:>6.2f}% ({wins_slice:02d}/{total_slice-wins_slice:02d}) | {pf_str_slice:>14} | {dd_slice:>9.2f}%")
        print("-" * 85)
    # --- FIM DO NOVO BLOCO ---
    
    generate_trades_html(results)
    
    # 1. Gráfico da Curva de Capital
    plt.figure(figsize=(10, 4))
    plt.plot(results['datetime'], results['equity'], color='#2ecc71')
    plt.title("Curva de Capital (Equity Curve)")
    plt.grid(True, alpha=0.3)
    plt.savefig('equity.png')
    print("[OK] 'equity.png' gerado com sucesso.")
    
    # 2. Gráfico de Candles com as operações
    plot_recent_trades_candlestick(df_base, results, days=30)

if __name__ == "__main__":
    df_b, df_s, s_p, e_p, t_min = load_and_resample(CSV_FILE_PATH, BASE_TF, SIGNAL_TF)
    if df_b is not None:
        report = run_backtest(df_b, df_s)
        show_report(report, df_b, s_p, e_p, t_min)