-- Test bot: needs one strategy row. Inserts stopped bot with minimal python if none exists for fixed id.
insert into public.bots (
  id,
  name,
  strategy_id,
  trading_pair,
  market_type,
  status,
  params,
  content,
  version_number
)
select
  '00000000-0000-0000-0000-000000000001'::uuid,
  'Test Bot BTC Scalper',
  s.id,
  'BTCUSDT.P',
  'linear',
  'stopped',
  '{"rsi_period": 14, "overbought": 70, "signal_amount": 0.001}'::jsonb,
  E'# placeholder — replace in Strategies UI\nclass Strategy:\n    def __init__(self, params):\n        self.p = params\n    def on_tick(self, market_data):\n        return None\n',
  1
from public.strategies s
order by s.created_at
limit 1
on conflict (id) do nothing;
