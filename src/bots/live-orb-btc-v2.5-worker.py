"""ORB live: NY 15m bars from ticks; worker injects `account_equity` (Bybit total in quote). Paste as `bots.content`."""
from __future__ import annotations

from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo

# --- tweak below (BASE_TF must equal SIGNAL_TF for this script) ---
BASE_TF = '15min'
SIGNAL_TF = '15min'

RISK_PER_TRADE_PCT = 1.0
MAX_LEVERAGE = 1.0

START_RANGE = '09:30'
RANGE_MINUTES = 15
END_OF_DAY = '23:59'
TRADE_DAYS = 'WEEKDAYS'

RISK_REWARD = 3.0
STOP_TYPE = 'OPPOSITE'
ENTRY_BUFFER_PCT = 0.02

ENTRY_TYPE = 'CLOSING'
ENTRY_PRICE_TYPE = 'RANGE_EXTREME'
USE_CONFIRMATION_BREAK = True

USE_ATR_FILTER = True
ATR_PERIOD = 14
MIN_RANGE_ATR_MULT = 1.0
USE_MAX_RANGE_FILTER = True
MAX_RANGE_PT = 2000

USE_VOLUME_FILTER = True
VOLUME_MA_PERIOD = 10
VOLUME_MULTIPLIER = 2.0

USE_BREAK_EVEN = True
BE_TRIGGER_RR = 1.0

MAX_TRADE_DURATION = 30

NY = ZoneInfo('America/New_York')


class Strategy:

    @staticmethod
    def _tf_minutes(tf: str) -> int:
        t = tf.strip().lower()
        if t.endswith('min'):
            return int(t[:-3])
        if t.endswith('m') and t[:-1].isdigit():
            return int(t[:-1])
        raise ValueError(f'unsupported tf {tf!r}')

    @staticmethod
    def _parse_hm(s: str) -> time:
        h, m = s.strip().split(':')
        return time(int(h), int(m))

    @staticmethod
    def _time_to_minutes(t: time) -> int:
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
    def _weekday_ok(d: datetime.date) -> bool:
        wd = d.weekday()
        if TRADE_DAYS == 'WEEKDAYS' and wd >= 5:
            return False
        if TRADE_DAYS == 'WEEKENDS' and wd < 5:
            return False
        if TRADE_DAYS == 'SATURDAY' and wd != 5:
            return False
        if TRADE_DAYS == 'SUNDAY' and wd != 6:
            return False
        return True

    def __init__(self, params: dict) -> None:
        self.p = params
        self._tfm = self._tf_minutes(BASE_TF)
        if self._tf_minutes(SIGNAL_TF) != self._tfm:
            raise ValueError('BASE_TF and SIGNAL_TF must match in this script.')
        self._start_range = self._parse_hm(START_RANGE)
        self._end_range = self._parse_hm(
            (datetime.strptime(START_RANGE, '%H:%M') + timedelta(minutes=RANGE_MINUTES)).strftime('%H:%M')
        )
        self._eod = self._parse_hm(END_OF_DAY)
        self._sr_m = self._time_to_minutes(self._start_range)
        self._er_m = self._time_to_minutes(self._end_range)
        self._eod_m = self._time_to_minutes(self._eod)

        self._bucket: datetime | None = None
        self._o = self._h = self._l = self._c = 0.0
        self._v_ticks = 0

        self._day: datetime.date | None = None
        self._today_bars: list[dict] = []

        self._r_high: float | None = None
        self._r_low: float | None = None
        self._range_ready = False
        self._day_valid = False
        self._day_done = False

        self.pos_type: str | None = None
        self.entry_time: datetime | None = None
        self.in_trade = False
        self.qty = 0.0
        self.is_be_active = False
        self.trigger_level: float | None = None
        self.entry_price_final: float | None = None
        self.sl: float | None = None
        self.tp: float | None = None
        self.leverage = 0.0
        self.current_equity = 0.0

    def _reset_day(self, d: datetime.date) -> None:
        self._day = d
        self._today_bars = []
        self._r_high = None
        self._r_low = None
        self._range_ready = False
        self._day_valid = False
        self._day_done = False
        self.pos_type = None
        self.entry_time = None
        self.in_trade = False
        self.qty = 0.0
        self.is_be_active = False
        self.trigger_level = None
        self.entry_price_final = None
        self.sl = None
        self.tp = None
        self.leverage = 0.0

    def _finalize_bar(self) -> dict | None:
        if self._bucket is None:
            return None
        return {
            'start': self._bucket,
            'o': self._o,
            'h': self._h,
            'l': self._l,
            'c': self._c,
            'v': float(self._v_ticks),
            'atr': None,
            'vol_ma': None,
        }

    def _roll_atr_vol(self, bars: list[dict]) -> None:
        trs: list[float] = []
        prev_c: float | None = None
        for b in bars:
            h, l, c = b['h'], b['l'], b['c']
            if prev_c is None:
                tr = h - l
            else:
                tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)
            prev_c = c
        for i, b in enumerate(bars):
            w = ATR_PERIOD
            if i + 1 >= w:
                b['atr'] = sum(trs[i + 1 - w : i + 1]) / w
            else:
                b['atr'] = None
            vw = VOLUME_MA_PERIOD
            if i + 1 >= vw:
                b['vol_ma'] = sum(bb['v'] for bb in bars[i + 1 - vw : i + 1]) / vw
            else:
                b['vol_ma'] = None

    def _in_range_window(self, bar_start: datetime) -> bool:
        m = self._time_to_minutes(bar_start.time())
        return self._sr_m <= m < self._er_m

    def _in_exec_window(self, bar_start: datetime) -> bool:
        m = self._time_to_minutes(bar_start.time())
        return m >= self._er_m and m <= self._eod_m

    def _process_closed_bar(self, e_idx: datetime, e_row: dict) -> dict | str | None:
        if self._day_done or not self._day_valid or not self._range_ready:
            return None

        o, h, l, c, v = e_row['o'], e_row['h'], e_row['l'], e_row['c'], e_row['v']
        atr, vol_ma = e_row.get('atr'), e_row.get('vol_ma')

        if self.pos_type is None:
            if not self._range_ready:
                return None
            l_trig = self._r_high * (1 + (ENTRY_BUFFER_PCT / 100)) if self._r_high is not None else None
            s_trig = self._r_low * (1 - (ENTRY_BUFFER_PCT / 100)) if self._r_low is not None else None
            if l_trig is None or s_trig is None:
                return None
            vol_ok = v >= (vol_ma * VOLUME_MULTIPLIER) if USE_VOLUME_FILTER and vol_ma is not None else (
                True if not USE_VOLUME_FILTER else False
            )

            is_trig_signal = False
            if vol_ok:
                if ENTRY_TYPE == 'CLOSING':
                    if c > l_trig:
                        self.pos_type, is_trig_signal = 'LONG', True
                    elif c < s_trig:
                        self.pos_type, is_trig_signal = 'SHORT', True
                else:
                    if h >= l_trig:
                        self.pos_type, is_trig_signal = 'LONG', True
                    elif l <= s_trig:
                        self.pos_type, is_trig_signal = 'SHORT', True

            if is_trig_signal:
                if ENTRY_PRICE_TYPE == 'PREV_CANDLE':
                    if len(self._today_bars) < 2:
                        return None
                    prev = self._today_bars[-2]
                    self.entry_price_final = prev['h'] if self.pos_type == 'LONG' else prev['l']
                else:
                    self.entry_price_final = l_trig if self.pos_type == 'LONG' else s_trig

                if USE_CONFIRMATION_BREAK:
                    self.trigger_level = h if self.pos_type == 'LONG' else l
                else:
                    self.trigger_level = self.entry_price_final
            return None

        if self.pos_type is not None and not self.in_trade:
            if (self.pos_type == 'LONG' and h >= self.trigger_level) or (
                self.pos_type == 'SHORT' and l <= self.trigger_level
            ):
                self.in_trade = True
                self.entry_time = e_idx
                rh, rl = self._r_high, self._r_low
                r_size = rh - rl
                if self.pos_type == 'LONG':
                    self.sl = (rl if STOP_TYPE == 'OPPOSITE' else (rl + r_size / 2))
                else:
                    self.sl = (rh if STOP_TYPE == 'OPPOSITE' else (rl + r_size / 2))
                dist = abs(self.entry_price_final - self.sl)
                if dist == 0:
                    dist = 1e-5
                self.tp = (
                    self.entry_price_final + (dist * RISK_REWARD)
                    if self.pos_type == 'LONG'
                    else self.entry_price_final - (dist * RISK_REWARD)
                )
                if self.current_equity <= 0:
                    return None
                self.qty = (self.current_equity * (RISK_PER_TRADE_PCT / 100.0)) / dist
                self.leverage = (self.qty * self.entry_price_final) / self.current_equity
                if self.leverage > MAX_LEVERAGE:
                    self.qty = (self.current_equity * MAX_LEVERAGE) / self.entry_price_final
                    self.leverage = MAX_LEVERAGE
                act = 'BUY' if self.pos_type == 'LONG' else 'SELL'
                return {'action': act, 'amount': float(self.qty)}
            return None

        if self.in_trade:
            exit_p = None
            if self.pos_type == 'LONG':
                if l <= self.sl:
                    exit_p = self.sl
                elif h >= self.tp:
                    exit_p = self.tp
            else:
                if h >= self.sl:
                    exit_p = self.sl
                elif l <= self.tp:
                    exit_p = self.tp

            if exit_p is None and USE_BREAK_EVEN and not self.is_be_active:
                dist_be = abs(self.entry_price_final - self.sl)
                if (self.pos_type == 'LONG' and h >= self.entry_price_final + (dist_be * BE_TRIGGER_RR)) or (
                    self.pos_type == 'SHORT' and l <= self.entry_price_final - (dist_be * BE_TRIGGER_RR)
                ):
                    self.sl, self.is_be_active = self.entry_price_final, True

            if exit_p is None and MAX_TRADE_DURATION > 0:
                if ((e_idx - self.entry_time).total_seconds() / 60.0) >= MAX_TRADE_DURATION:
                    exit_p = c
            if exit_p is None and e_idx.time() >= datetime.strptime(END_OF_DAY, '%H:%M').time():
                exit_p = c

            if exit_p:
                self._day_done = True
                close_act = 'CLOSE_LONG' if self.pos_type == 'LONG' else 'CLOSE_SHORT'
                return {'action': close_act, 'amount': float(self.qty)}
        return None

    def _on_new_closed_bar(self, bar: dict) -> dict | str | None:
        d = bar['start'].date()
        if self._day != d:
            self._reset_day(d)

        if not self._weekday_ok(d):
            self._today_bars.append(bar)
            self._roll_atr_vol(self._today_bars)
            return None

        bm = self._time_to_minutes(bar['start'].time())

        if self._in_range_window(bar['start']):
            if self._r_high is None:
                self._r_high, self._r_low = bar['h'], bar['l']
            else:
                self._r_high = max(self._r_high, bar['h'])
                self._r_low = min(self._r_low, bar['l'])

        self._today_bars.append(bar)
        self._roll_atr_vol(self._today_bars)

        if not self._range_ready and bm >= self._er_m:
            r_size = (self._r_high - self._r_low) if self._r_high is not None else 0
            if self._r_high is None or self._r_low is None or r_size <= 0:
                self._day_valid = False
                self._range_ready = True
                return None
            if USE_ATR_FILTER:
                last_range_bar = None
                for b in reversed(self._today_bars[:-1]):
                    if self._in_range_window(b['start']):
                        last_range_bar = b
                        break
                current_atr = last_range_bar.get('atr') if last_range_bar else None
                if current_atr is None or r_size < (current_atr * MIN_RANGE_ATR_MULT):
                    self._day_valid = False
                    self._range_ready = True
                    return None
            if USE_MAX_RANGE_FILTER and r_size > MAX_RANGE_PT:
                self._day_valid = False
                self._range_ready = True
                return None
            self._day_valid = True
            self._range_ready = True

        if not self._in_exec_window(bar['start']):
            return None
        if not self._day_valid:
            return None

        return self._process_closed_bar(bar['start'], bar)

    def on_tick(self, market_data: dict) -> dict | str | None:
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
        bstart = self._bar_start_ny(ts, self._tfm)

        if self._bucket is None:
            self._bucket = bstart
            self._o = self._h = self._l = self._c = px
            self._v_ticks = 1
            return None

        if bstart != self._bucket:
            closed = self._finalize_bar()
            out = None
            if closed is not None:
                out = self._on_new_closed_bar(closed)
            self._bucket = bstart
            self._o = self._h = self._l = self._c = px
            self._v_ticks = 1
            return out

        self._h = max(self._h, px)
        self._l = min(self._l, px)
        self._c = px
        self._v_ticks += 1
        return None
