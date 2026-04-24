"""ORB live: NY session logic on BASE_TF; worker kline vol uses same TF (BASE_TF) unless overridden in `bots.params`. Injects `account_equity` (Bybit). Paste as `bots.content`."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, time as dtime, timezone
from zoneinfo import ZoneInfo

# --- tweak below (BASE_TF must equal SIGNAL_TF for this script) ---
BASE_TF = '1min'
SIGNAL_TF = '1min'

RISK_PER_TRADE_PCT = 1.0
MAX_LEVERAGE = 1.0

START_RANGE   = '15:05'
RANGE_MINUTES = 5
END_OF_DAY    = '23:59'
TRADE_DAYS    = 'WEEKDAYS'

RISK_REWARD       = 3.0
STOP_TYPE         = 'OPPOSITE'
ENTRY_BUFFER_PCT  = 0.02

ENTRY_TYPE         = 'TOUCHING'
ENTRY_PRICE_TYPE   = 'PREV_CANDLE'
USE_CONFIRMATION_BREAK = False

USE_ATR_FILTER      = False
ATR_PERIOD          = 14
MIN_RANGE_ATR_MULT  = 1.0
USE_MAX_RANGE_FILTER = True
MAX_RANGE_PT        = 2000

USE_VOLUME_FILTER  = False
VOLUME_MA_PERIOD   = 10
VOLUME_MULTIPLIER  = 2.0

USE_BREAK_EVEN  = False
BE_TRIGGER_RR   = 1.0

MAX_TRADE_DURATION = 30

NY = ZoneInfo('America/New_York')

# Throttle para o heartbeat periódico (não afeta logs de transição)
ORB_LOG_SEC = float((os.environ.get("ORB_LOG_SEC") or "30.0").strip() or "30.0")


# ─────────────────────────────────────────────────────────────────
# Helpers de formatação
# ─────────────────────────────────────────────────────────────────

def _p(v) -> str:
    """Formata preço."""
    return "—" if v is None else f"{float(v):,.2f}"

def _q(v) -> str:
    """Formata quantidade."""
    return "—" if v is None else f"{float(v):.6f}"

def _vol(v) -> str:
    """Formata volume."""
    return "—" if v is None else f"{float(v):.4f}"


class Strategy:

    # ──────────────────────────────────────────────────────────────
    # Static helpers
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _tf_minutes(tf: str) -> int:
        t = tf.strip().lower()
        if t.endswith('min'):
            return int(t[:-3])
        if t.endswith('m') and t[:-1].isdigit():
            return int(t[:-1])
        raise ValueError(f'unsupported tf {tf!r}')

    @staticmethod
    def _parse_hm(s: str) -> dtime:
        h, m = s.strip().split(':')
        return dtime(int(h), int(m))

    @staticmethod
    def _time_to_minutes(t: dtime) -> int:
        return t.hour * 60 + t.minute

    @staticmethod
    def _bar_start_ny(ts_ms: int, tf_minutes: int) -> datetime:
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).astimezone(NY)
        dt = dt.replace(second=0, microsecond=0)
        mins = dt.hour * 60 + dt.minute
        floored = (mins // tf_minutes) * tf_minutes
        hh, mm = divmod(floored, 60)
        return dt.replace(hour=hh, minute=mm)

    @staticmethod
    def _weekday_ok(d) -> bool:
        wd = d.weekday()
        if TRADE_DAYS == 'WEEKDAYS' and wd >= 5:   return False
        if TRADE_DAYS == 'WEEKENDS' and wd < 5:    return False
        if TRADE_DAYS == 'SATURDAY' and wd != 5:   return False
        if TRADE_DAYS == 'SUNDAY'   and wd != 6:   return False
        return True

    # ──────────────────────────────────────────────────────────────
    # Init
    # ──────────────────────────────────────────────────────────────

    def __init__(self, params: dict) -> None:
        self.p    = params
        self._tfm = self._tf_minutes(BASE_TF)
        if self._tf_minutes(SIGNAL_TF) != self._tfm:
            raise ValueError('BASE_TF and SIGNAL_TF must match in this script.')

        range_end_str = (
            datetime.strptime(START_RANGE, '%H:%M') + timedelta(minutes=RANGE_MINUTES)
        ).strftime('%H:%M')

        self._start_range = self._parse_hm(START_RANGE)
        self._end_range   = self._parse_hm(range_end_str)
        self._eod         = self._parse_hm(END_OF_DAY)
        self._sr_m  = self._time_to_minutes(self._start_range)
        self._er_m  = self._time_to_minutes(self._end_range)
        self._eod_m = self._time_to_minutes(self._eod)

        # Barra em construção
        self._bucket: datetime | None = None
        self._o = self._h = self._l = self._c = 0.0
        self._v_ticks: float = 0.0

        # Estado do dia
        self._day: datetime.date | None = None
        self._today_bars: list[dict]    = []
        self._r_high: float | None      = None
        self._r_low:  float | None      = None
        self._range_ready  = False
        self._day_valid    = False
        self._day_done     = False

        # Estado da posição
        self.pos_type:          str | None      = None
        self.entry_time:        datetime | None = None
        self.in_trade           = False
        self.qty                = 0.0
        self.is_be_active       = False
        self.trigger_level:     float | None = None
        self.entry_price_final: float | None = None
        self.sl:                float | None = None
        self.tp:                float | None = None
        self.leverage           = 0.0
        self.current_equity     = 0.0

        self._last_market: dict = {}
        self._log = logging.getLogger("orb")
        self._status_last_m: float = 0.0

        # Flags de log de transição (disparam apenas uma vez por evento)
        self._logged_pre_range    = False   # "aguardando janela de range"
        self._logged_range_start  = False   # "iniciando mapeamento"
        self._logged_range_end    = False   # "range mapeado"
        self._logged_day_invalid  = False   # "dia inválido"
        self._logged_exec_open    = False   # "janela exec aberta"
        self._logged_signal       = False   # "sinal detectado"
        self._logged_order        = False   # "ordem enviada"
        self._logged_be           = False   # "break-even ativado"

        self._log_startup(range_end_str)

    # ──────────────────────────────────────────────────────────────
    # Log de startup (uma vez)
    # ──────────────────────────────────────────────────────────────

    def _log_startup(self, range_end_str: str) -> None:
        L = self._log
        L.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        L.info("▶  ORB STRATEGY CARREGADA")
        L.info("   TF: %s  |  Janela range (NY): %s → %s (%d min)", BASE_TF, START_RANGE, range_end_str, RANGE_MINUTES)
        L.info("   Dias válidos: %s  |  Fim do dia: %s", TRADE_DAYS, END_OF_DAY)
        L.info("   Risco: %.1f%%/trade  |  Alavancagem máx: %.1fx  |  R:R alvo: %.1f", RISK_PER_TRADE_PCT, MAX_LEVERAGE, RISK_REWARD)
        L.info("   Stop: %s  |  Buffer entrada: %.2f%%", STOP_TYPE, ENTRY_BUFFER_PCT)
        L.info("   Tipo entrada: %s  |  Preço ref: %s  |  Confirmação barra: %s",
               ENTRY_TYPE, ENTRY_PRICE_TYPE, USE_CONFIRMATION_BREAK)
        L.info("   Filtro ATR: %s (P=%d, range ≥ ATR×%.1f)", "ON" if USE_ATR_FILTER else "off", ATR_PERIOD, MIN_RANGE_ATR_MULT)
        L.info("   Filtro max range: %s (máx %.0f pts)", "ON" if USE_MAX_RANGE_FILTER else "off", MAX_RANGE_PT)
        L.info("   Filtro volume: %s (MA %d, ×%.1f)", "ON" if USE_VOLUME_FILTER else "off", VOLUME_MA_PERIOD, VOLUME_MULTIPLIER)
        L.info("   Break-even: %s (gatilho R=%.1f)  |  Max duração: %d min", "ON" if USE_BREAK_EVEN else "off", BE_TRIGGER_RR, MAX_TRADE_DURATION)
        L.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # ──────────────────────────────────────────────────────────────
    # Heartbeat periódico (throttled — não confundir com transições)
    # ──────────────────────────────────────────────────────────────

    def _heartbeat(self, now_ny: datetime, px: float) -> None:
        mono = time.monotonic()
        if mono - self._status_last_m < ORB_LOG_SEC:
            return
        self._status_last_m = mono

        cur_m = self._time_to_minutes(now_ny.time())

        if not self._weekday_ok(now_ny.date()):
            self._log.info("[heartbeat] %s  px=%s  dia=%s → não opera (%s)", now_ny.strftime("%H:%M NY"), _p(px), now_ny.strftime("%A"), TRADE_DAYS)
            return

        if cur_m < self._sr_m:
            mins_left = self._sr_m - cur_m
            self._log.info("[heartbeat] %s  px=%s  → aguardando janela de range (%s, em %d min)",
                           now_ny.strftime("%H:%M NY"), _p(px), START_RANGE, mins_left)
            return

        if self._sr_m <= cur_m < self._er_m:
            r_sz = (_p(self._r_high - self._r_low) if self._r_high and self._r_low else "—")
            self._log.info("[heartbeat] %s  px=%s  → MAPEANDO RANGE  high=%s  low=%s  tamanho=%s",
                           now_ny.strftime("%H:%M NY"), _p(px), _p(self._r_high), _p(self._r_low), r_sz)
            return

        if not self._range_ready:
            self._log.info("[heartbeat] %s  px=%s  → range ainda não finalizado (aguardando barra fechar)",
                           now_ny.strftime("%H:%M NY"), _p(px))
            return

        if not self._day_valid:
            self._log.info("[heartbeat] %s  px=%s  → dia INVÁLIDO (filtros reprovaram) — sem trade hoje",
                           now_ny.strftime("%H:%M NY"), _p(px))
            return

        if self._day_done:
            self._log.info("[heartbeat] %s  px=%s  → dia concluído (trade executado + encerrado)",
                           now_ny.strftime("%H:%M NY"), _p(px))
            return

        # Janela de execução
        l_trig = self._r_high * (1 + ENTRY_BUFFER_PCT / 100) if self._r_high else None
        s_trig = self._r_low  * (1 - ENTRY_BUFFER_PCT / 100) if self._r_low  else None

        if not self.in_trade and self.pos_type is None:
            self._log.info("[heartbeat] %s  px=%s  → AGUARDANDO SINAL  trig_long=%s  trig_short=%s",
                           now_ny.strftime("%H:%M NY"), _p(px), _p(l_trig), _p(s_trig))
        elif not self.in_trade:
            self._log.info("[heartbeat] %s  px=%s  → SINAL %s aguardando confirmação  gatilho=%s",
                           now_ny.strftime("%H:%M NY"), _p(px), self.pos_type, _p(self.trigger_level))
        else:
            dur = (now_ny - self.entry_time).total_seconds() / 60.0 if self.entry_time else 0
            self._log.info(
                "[heartbeat] %s  px=%s  → EM POSIÇÃO %s  entrada=%s  SL=%s  TP=%s  BE=%s  dur=%.0fmin",
                now_ny.strftime("%H:%M NY"), _p(px), self.pos_type,
                _p(self.entry_price_final), _p(self.sl), _p(self.tp),
                "ativo" if self.is_be_active else "pendente", dur,
            )

    # ──────────────────────────────────────────────────────────────
    # Reset diário
    # ──────────────────────────────────────────────────────────────

    def _reset_day(self, d) -> None:
        self._log.info("━━ NOVO DIA: %s (%s) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", d.isoformat(), d.strftime("%A"))
        self._day        = d
        self._today_bars = []
        self._r_high = self._r_low = None
        self._range_ready = self._day_valid = self._day_done = False
        self.pos_type = self.entry_time = None
        self.in_trade = self.is_be_active = False
        self.qty = self.leverage = 0.0
        self.trigger_level = self.entry_price_final = self.sl = self.tp = None
        # Reset flags de transição
        self._logged_pre_range   = False
        self._logged_range_start = False
        self._logged_range_end   = False
        self._logged_day_invalid = False
        self._logged_exec_open   = False
        self._logged_signal      = False
        self._logged_order       = False
        self._logged_be          = False

    # ──────────────────────────────────────────────────────────────
    # Construção de barras
    # ──────────────────────────────────────────────────────────────

    def _finalize_bar(self) -> dict | None:
        if self._bucket is None:
            return None
        return {'start': self._bucket, 'o': self._o, 'h': self._h,
                'l': self._l, 'c': self._c, 'v': float(self._v_ticks),
                'atr': None, 'vol_ma': None}

    def _roll_atr_vol(self, bars: list[dict]) -> None:
        trs, prev_c = [], None
        for b in bars:
            h, l, c = b['h'], b['l'], b['c']
            tr = (h - l) if prev_c is None else max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)
            prev_c = c
        for i, b in enumerate(bars):
            b['atr']    = sum(trs[i + 1 - ATR_PERIOD    : i + 1]) / ATR_PERIOD    if i + 1 >= ATR_PERIOD    else None
            b['vol_ma'] = sum(bb['v'] for bb in bars[i + 1 - VOLUME_MA_PERIOD : i + 1]) / VOLUME_MA_PERIOD if i + 1 >= VOLUME_MA_PERIOD else None

    def _in_range_window(self, bar_start: datetime) -> bool:
        m = self._time_to_minutes(bar_start.time())
        return self._sr_m <= m < self._er_m

    def _in_exec_window(self, bar_start: datetime) -> bool:
        m = self._time_to_minutes(bar_start.time())
        return self._er_m <= m <= self._eod_m

    # ──────────────────────────────────────────────────────────────
    # Processamento de barras fechadas
    # ──────────────────────────────────────────────────────────────

    def _on_new_closed_bar(self, bar: dict) -> dict | str | None:
        d = bar['start'].date()
        if self._day != d:
            self._reset_day(d)

        # Fim de semana / dia inválido
        if not self._weekday_ok(d):
            self._today_bars.append(bar)
            self._roll_atr_vol(self._today_bars)
            return None

        bm = self._time_to_minutes(bar['start'].time())

        # ── PRÉ-RANGE: log de aviso quando a primeira barra do dia chega antes do range ──
        if bm < self._sr_m and not self._logged_pre_range:
            self._log.info(
                "[transição] PRÉ-RANGE: recebendo barras do dia %s (barra atual: %s NY). "
                "Mapeamento começa em %s NY. Nenhuma ação até lá.",
                d.isoformat(),
                bar['start'].strftime("%H:%M"),
                START_RANGE,
            )
            self._logged_pre_range = True

        # ── MAPEAMENTO DE RANGE ────────────────────────────────────────────────
        if self._in_range_window(bar['start']):
            if not self._logged_range_start:
                self._log.info(
                    "[transição] INÍCIO MAPEAMENTO RANGE  barra=%s NY  janela=%s→%s (%dmin TF=%s)",
                    bar['start'].strftime("%H:%M"),
                    START_RANGE,
                    (datetime.strptime(START_RANGE, '%H:%M') + timedelta(minutes=RANGE_MINUTES)).strftime('%H:%M'),
                    RANGE_MINUTES,
                    BASE_TF,
                )
                self._logged_range_start = True

            prev_h, prev_l = self._r_high, self._r_low
            if self._r_high is None:
                self._r_high, self._r_low = bar['h'], bar['l']
            else:
                self._r_high = max(self._r_high, bar['h'])
                self._r_low  = min(self._r_low,  bar['l'])

            # Log de cada barra do range
            self._log.info(
                "[range] barra %s  O=%s H=%s L=%s C=%s V=%s  |  range acumulado: [%s, %s] (%.2f pts)",
                bar['start'].strftime("%H:%M"),
                _p(bar['o']), _p(bar['h']), _p(bar['l']), _p(bar['c']), _vol(bar['v']),
                _p(self._r_low), _p(self._r_high),
                (self._r_high - self._r_low) if self._r_high and self._r_low else 0,
            )

        self._today_bars.append(bar)
        self._roll_atr_vol(self._today_bars)

        # ── FIM DO MAPEAMENTO: valida filtros ─────────────────────────────────
        if not self._range_ready and bm >= self._er_m:
            r_size = (self._r_high - self._r_low) if self._r_high is not None and self._r_low is not None else 0

            if not self._logged_range_end:
                self._log.info(
                    "[transição] FIM MAPEAMENTO RANGE  mín=%s  máx=%s  tamanho=%.2f pts",
                    _p(self._r_low), _p(self._r_high), r_size,
                )
                self._logged_range_end = True

            # Validação: range vazio
            if self._r_high is None or self._r_low is None or r_size <= 0:
                self._day_valid = False
                self._range_ready = True
                if not self._logged_day_invalid:
                    self._log.warning("[filtro] REPROVADO — range vazio ou zerado. Nenhum trade hoje.")
                    self._logged_day_invalid = True
                return None

            # Validação: filtro ATR
            if USE_ATR_FILTER:
                last_range_bar = next((b for b in reversed(self._today_bars[:-1]) if self._in_range_window(b['start'])), None)
                current_atr = last_range_bar.get('atr') if last_range_bar else None
                atr_needed  = (current_atr or 0) * MIN_RANGE_ATR_MULT
                atr_ok      = current_atr is not None and r_size >= atr_needed
                self._log.info(
                    "[filtro] ATR: range=%.2f  ATR=%.2f  necessário≥%.2f  → %s",
                    r_size, current_atr or 0, atr_needed,
                    "✅ OK" if atr_ok else "❌ REPROVADO",
                )
                if not atr_ok:
                    self._day_valid = False
                    self._range_ready = True
                    if not self._logged_day_invalid:
                        self._log.warning("[filtro] REPROVADO pelo ATR. Nenhum trade hoje.")
                        self._logged_day_invalid = True
                    return None
            else:
                self._log.info("[filtro] ATR: desativado (off)")

            # Validação: max range
            if USE_MAX_RANGE_FILTER:
                max_ok = r_size <= MAX_RANGE_PT
                self._log.info(
                    "[filtro] Max range: range=%.2f  máx=%.0f pts  → %s",
                    r_size, MAX_RANGE_PT,
                    "✅ OK" if max_ok else "❌ REPROVADO",
                )
                if not max_ok:
                    self._day_valid = False
                    self._range_ready = True
                    if not self._logged_day_invalid:
                        self._log.warning("[filtro] REPROVADO pelo max range. Nenhum trade hoje.")
                        self._logged_day_invalid = True
                    return None
            else:
                self._log.info("[filtro] Max range: desativado (off)")

            # Todos os filtros passaram
            self._day_valid   = True
            self._range_ready = True
            l_trig = self._r_high * (1 + ENTRY_BUFFER_PCT / 100)
            s_trig = self._r_low  * (1 - ENTRY_BUFFER_PCT / 100)

            if not self._logged_exec_open:
                self._log.info(
                    "[transição] ✅ DIA VÁLIDO — todos os filtros aprovados. Janela de execução ABERTA."
                )
                self._log.info(
                    "[execução] range=[%s, %s] (%.2f pts)  buffer=%.2f%%",
                    _p(self._r_low), _p(self._r_high), r_size, ENTRY_BUFFER_PCT,
                )
                self._log.info(
                    "[execução] gatilho LONG (breakout ↑): %s  |  gatilho SHORT (breakout ↓): %s",
                    _p(l_trig), _p(s_trig),
                )
                self._log.info(
                    "[execução] aguardando barra fechar além dos gatilhos (ENTRY_TYPE=%s, CONFIRMATION=%s)",
                    ENTRY_TYPE, USE_CONFIRMATION_BREAK,
                )
                self._logged_exec_open = True

        # Só processa lógica de entrada/saída se na janela de execução
        if not self._in_exec_window(bar['start']) or not self._day_valid:
            return None

        return self._process_closed_bar(bar['start'], bar)

    # ──────────────────────────────────────────────────────────────
    # Lógica de entrada / saída (chamada apenas na janela de exec)
    # ──────────────────────────────────────────────────────────────

    def _process_closed_bar(self, e_idx: datetime, e_row: dict) -> dict | str | None:
        if self._day_done or not self._day_valid or not self._range_ready:
            return None

        h, l, c, v = e_row['h'], e_row['l'], e_row['c'], e_row['v']
        vol_ma = e_row.get('vol_ma')
        ex_ma  = (self._last_market or {}).get("candle_closed_vol_ma_10")

        # ── Aguardando sinal inicial ───────────────────────────────────────
        if self.pos_type is None:
            l_trig = self._r_high * (1 + ENTRY_BUFFER_PCT / 100)
            s_trig = self._r_low  * (1 - ENTRY_BUFFER_PCT / 100)

            # Filtro de volume (por barra)
            if USE_VOLUME_FILTER:
                ref    = ex_ma if ex_ma is not None else vol_ma
                vol_ok = (v >= ref * VOLUME_MULTIPLIER) if ref is not None else False
                self._log.info(
                    "[filtro] Volume barra %s: vol=%.4f  ref=%.4f  needed=%.4f  → %s",
                    e_idx.strftime("%H:%M"), v, ref or 0, (ref or 0) * VOLUME_MULTIPLIER,
                    "✅ OK" if vol_ok else "❌ insuficiente (sem sinal nesta barra)",
                )
            else:
                vol_ok = True

            if not vol_ok:
                return None

            # Verifica breakout
            triggered = False
            if ENTRY_TYPE == 'CLOSING':
                if   c > l_trig: self.pos_type, triggered = 'LONG',  True
                elif c < s_trig: self.pos_type, triggered = 'SHORT', True
            else:  # TOUCHING
                if   h >= l_trig: self.pos_type, triggered = 'LONG',  True
                elif l <= s_trig: self.pos_type, triggered = 'SHORT', True

            if triggered:
                # Preço de referência de entrada
                if ENTRY_PRICE_TYPE == 'PREV_CANDLE':
                    if len(self._today_bars) < 2:
                        self._log.warning("[sinal] sem barra anterior para PREV_CANDLE — ignorando")
                        self.pos_type = None
                        return None
                    prev = self._today_bars[-2]
                    self.entry_price_final = prev['h'] if self.pos_type == 'LONG' else prev['l']
                else:
                    self.entry_price_final = l_trig if self.pos_type == 'LONG' else s_trig

                # Nível de confirmação
                if USE_CONFIRMATION_BREAK:
                    self.trigger_level = h if self.pos_type == 'LONG' else l
                else:
                    self.trigger_level = self.entry_price_final

                if not self._logged_signal:
                    self._log.info(
                        "[transição] 🔍 SINAL %s  barra=%s  |  px_ref_entrada=%s  "
                        "gatilho_conf=%s  (conf_break=%s  entry_type=%s  preço_ref=%s)",
                        self.pos_type, e_idx.strftime("%H:%M"),
                        _p(self.entry_price_final), _p(self.trigger_level),
                        USE_CONFIRMATION_BREAK, ENTRY_TYPE, ENTRY_PRICE_TYPE,
                    )
                    if USE_CONFIRMATION_BREAK:
                        self._log.info(
                            "[sinal] aguardando próxima barra fechar além de %s para confirmar entrada",
                            _p(self.trigger_level),
                        )
                    self._logged_signal = True
            return None

        # ── Confirmação da entrada ─────────────────────────────────────────
        if self.pos_type is not None and not self.in_trade:
            conf = (self.pos_type == 'LONG'  and h >= self.trigger_level) or \
                   (self.pos_type == 'SHORT' and l <= self.trigger_level)
            if not conf:
                return None

            self.in_trade   = True
            self.entry_time = e_idx
            r_size = self._r_high - self._r_low

            self.sl = (self._r_low  if STOP_TYPE == 'OPPOSITE' else self._r_low  + r_size / 2) if self.pos_type == 'LONG' \
                 else (self._r_high if STOP_TYPE == 'OPPOSITE' else self._r_low  + r_size / 2)

            dist = max(abs(self.entry_price_final - self.sl), 1e-5)
            self.tp = (self.entry_price_final + dist * RISK_REWARD) if self.pos_type == 'LONG' \
                 else (self.entry_price_final - dist * RISK_REWARD)

            if self.current_equity <= 0:
                self._log.warning(
                    "[ordem] ⚠ account_equity=0 ou ausente — qty não calculável. "
                    "Verifique BYBIT_API_KEY + BYBIT_API_SECRET no serviço Worker do Railway."
                )
                return None

            self.qty      = (self.current_equity * RISK_PER_TRADE_PCT / 100.0) / dist
            self.leverage = (self.qty * self.entry_price_final) / self.current_equity
            if self.leverage > MAX_LEVERAGE:
                self.qty      = (self.current_equity * MAX_LEVERAGE) / self.entry_price_final
                self.leverage = MAX_LEVERAGE

            act = 'BUY' if self.pos_type == 'LONG' else 'SELL'

            if not self._logged_order:
                dist_tp = abs(self.tp - self.entry_price_final)
                self._log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                self._log.info("[transição] 🚀 ORDEM %s  barra=%s NY", act, e_idx.strftime("%Y-%m-%d %H:%M"))
                self._log.info("[ordem] entrada=%s  SL=%s  TP=%s",
                               _p(self.entry_price_final), _p(self.sl), _p(self.tp))
                self._log.info("[ordem] dist SL=%.2f pts  dist TP=%.2f pts  R:R efetivo=%.2f",
                               dist, dist_tp, dist_tp / dist if dist else 0)
                self._log.info("[ordem] qty=%s  notional=%s  alavancagem=%.2fx  equity=%s",
                               _q(self.qty), _p(self.qty * self.entry_price_final),
                               self.leverage, _p(self.current_equity))
                self._log.info("[ordem] risco $=%.2f  (%.1f%% de %s)",
                               dist * self.qty, RISK_PER_TRADE_PCT, _p(self.current_equity))
                self._log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                self._logged_order = True

            return {'action': act, 'amount': float(self.qty)}

        # ── Gestão da posição aberta ───────────────────────────────────────
        if self.in_trade:
            exit_p = exit_reason = None

            if self.pos_type == 'LONG':
                if l <= self.sl:   exit_p, exit_reason = self.sl, "SL atingido"
                elif h >= self.tp: exit_p, exit_reason = self.tp, "TP atingido"
            else:
                if h >= self.sl:   exit_p, exit_reason = self.sl, "SL atingido"
                elif l <= self.tp: exit_p, exit_reason = self.tp, "TP atingido"

            # Break-even
            if exit_p is None and USE_BREAK_EVEN and not self.is_be_active:
                dist_be    = abs(self.entry_price_final - self.sl)
                be_trigger = (self.entry_price_final + dist_be * BE_TRIGGER_RR) if self.pos_type == 'LONG' \
                        else (self.entry_price_final - dist_be * BE_TRIGGER_RR)
                hit_be = (self.pos_type == 'LONG' and h >= be_trigger) or \
                         (self.pos_type == 'SHORT' and l <= be_trigger)
                if hit_be:
                    self.sl, self.is_be_active = self.entry_price_final, True
                    if not self._logged_be:
                        self._log.info(
                            "[transição] 🔒 BREAK-EVEN ATIVADO  novo SL=%s (entrada)  gatilho era=%s",
                            _p(self.sl), _p(be_trigger),
                        )
                        self._logged_be = True

            # Saída por tempo
            if exit_p is None and MAX_TRADE_DURATION > 0:
                dur_min = (e_idx - self.entry_time).total_seconds() / 60.0
                if dur_min >= MAX_TRADE_DURATION:
                    exit_p, exit_reason = c, f"duração máx ({MAX_TRADE_DURATION}min) expirada — {dur_min:.0f}min"

            # Saída por EOD
            if exit_p is None and e_idx.time() >= self._eod:
                exit_p, exit_reason = c, "fim do dia (EOD)"

            if exit_p is not None:
                self._day_done = True
                close_act  = 'CLOSE_LONG' if self.pos_type == 'LONG' else 'CLOSE_SHORT'
                pnl_approx = (exit_p - self.entry_price_final) * self.qty * (1 if self.pos_type == 'LONG' else -1)
                self._log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                self._log.info("[transição] 🔴 SAÍDA %s  motivo: %s", close_act, exit_reason)
                self._log.info("[saída] preço_ref=%s  entrada=%s  PnL≈%s  qty=%s",
                               _p(exit_p), _p(self.entry_price_final), _p(pnl_approx), _q(self.qty))
                self._log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                return {'action': close_act, 'amount': float(self.qty)}

        return None

    # ──────────────────────────────────────────────────────────────
    # on_tick — ponto de entrada do Worker
    # ──────────────────────────────────────────────────────────────

    def on_tick(self, market_data: dict) -> dict | str | None:
        self._last_market = market_data

        # Atualiza equity
        eq = market_data.get('account_equity')
        if eq is not None:
            try:
                self.current_equity = float(eq)
            except (TypeError, ValueError):
                pass

        ts = int(market_data.get('timestamp') or 0)
        px = market_data.get('price')
        if ts <= 0 or px is None:
            return None
        px = float(px)

        bstart  = self._bar_start_ny(ts, self._tfm)
        now_ny  = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).astimezone(NY)

        # Acumula volume da barra em construção
        c_cum = market_data.get('candle_base_volume')
        use_cum: float | None = None
        if c_cum is not None:
            try:
                use_cum = max(0.0, float(c_cum))
            except (TypeError, ValueError):
                pass
        v_inc = 1.0
        if use_cum is None:
            dv = market_data.get('candle_base_volume_delta')
            if dv is not None:
                try:
                    v_inc = max(0.0, float(dv))
                except (TypeError, ValueError):
                    pass

        # Primeiro tick
        if self._bucket is None:
            self._bucket = bstart
            self._o = self._h = self._l = self._c = px
            self._v_ticks = use_cum if use_cum is not None else v_inc
            self._heartbeat(now_ny, px)
            return None

        # Barra nova: fecha a anterior e processa
        if bstart != self._bucket:
            closed = self._finalize_bar()
            out    = self._on_new_closed_bar(closed) if closed else None
            # Abre nova barra
            self._bucket  = bstart
            self._o = self._h = self._l = self._c = px
            self._v_ticks = use_cum if use_cum is not None else v_inc
            self._heartbeat(now_ny, px)
            return out

        # Intra-barra: só atualiza OHLCV
        self._h = max(self._h, px)
        self._l = min(self._l, px)
        self._c = px
        self._v_ticks = use_cum if use_cum is not None else (self._v_ticks + v_inc)
        self._heartbeat(now_ny, px)
        return None