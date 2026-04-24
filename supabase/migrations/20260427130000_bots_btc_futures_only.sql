-- Product scope: Bitcoin USDT linear perps only.

alter table public.bots drop constraint if exists bots_pair_format;

update public.bots
set
  trading_pair = 'BTCUSDT',
  market_type = 'linear';

alter table public.bots
  add constraint bots_pair_format check (trading_pair = 'BTCUSDT');

comment on column public.bots.trading_pair is
  'Fixed: BTCUSDT (Bitcoin USDT linear perp). Redis market_data:BTCUSDT; hub/worker map to CCXT BTC/USDT:USDT.';
