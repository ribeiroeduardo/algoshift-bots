-- Risk sizing lives in strategy code / bots.params JSON, not dedicated columns.

alter table public.bots drop column if exists max_order_size;
alter table public.bots drop column if exists max_notional_usd;
alter table public.bots drop column if exists max_open_positions;
