-- trading_pair: Bybit-style (BTCUSDT, BTCUSDT.P). Legacy BASE/QUOTE still valid for old rows.

alter table public.bots drop constraint if exists bots_pair_format;

update public.bots
set trading_pair = upper(replace(trading_pair, '/', ''))
where trading_pair ~ '.+/.+'
  and trading_pair !~ ':';

alter table public.bots
  add constraint bots_pair_format check (
    trading_pair ~ '^[A-Z0-9]{5,}$'
    or trading_pair ~ '^[A-Z0-9]{3,}\.P$'
    or trading_pair ~ '^[A-Z0-9]+/[A-Z0-9]+(:[A-Z0-9]+)?$'
  );

comment on column public.bots.trading_pair is
  'Bybit symbol as in UI: BTCUSDT (spot or linear per market_type) or BTCUSDT.P (linear perp). Redis channel market_data:{trading_pair}. Legacy CCXT BASE/QUOTE allowed.';
