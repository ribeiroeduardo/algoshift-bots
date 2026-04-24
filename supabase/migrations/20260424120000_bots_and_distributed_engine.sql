-- Bots, heartbeats, trades; RLS; idempotency index

do $$ begin
  create type public.bot_status as enum (
    'stopped',
    'running',
    'paused',
    'error'
  );
exception
  when duplicate_object then null;
end $$;

create table if not exists public.bots (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  strategy_id uuid not null references public.strategies (id) on delete restrict,
  active_version_id uuid references public.strategy_versions (id) on delete set null,
  trading_pair text not null,
  exchange text not null default 'bybit',
  market_type text not null default 'spot' check (market_type in ('spot', 'linear', 'inverse')),
  status public.bot_status not null default 'stopped',
  max_order_size numeric(20, 8) not null default 0,
  max_notional_usd numeric(20, 2) not null default 0,
  max_open_positions smallint not null default 1,
  params jsonb not null default '{}'::jsonb,
  last_error text,
  last_error_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint bots_pair_format check (trading_pair ~ '^[A-Z0-9]+/[A-Z0-9]+$')
);

create index if not exists idx_bots_status on public.bots (status);
create index if not exists idx_bots_strategy_id on public.bots (strategy_id);
create index if not exists idx_bots_trading_pair on public.bots (trading_pair);

create table if not exists public.bot_heartbeats (
  bot_id uuid primary key references public.bots (id) on delete cascade,
  last_heartbeat_at timestamptz not null default now(),
  worker_instance_id text,
  worker_version text,
  last_tick_at timestamptz,
  last_signal_at timestamptz,
  updated_at timestamptz not null default now()
);

create table if not exists public.trades (
  id uuid primary key default gen_random_uuid(),
  signal_id uuid,
  bot_id uuid references public.bots (id) on delete set null,
  versao_id uuid references public.strategy_versions (id) on delete set null,
  par_negociacao text not null,
  direcao text not null,
  preco_entrada numeric(20, 8),
  resultado text,
  exchange_order_id text,
  quantity numeric(20, 8),
  notional_usd numeric(20, 2),
  fee_usd numeric(20, 4),
  exit_price numeric(20, 8),
  pnl_usd numeric(20, 2),
  opened_at timestamptz default now(),
  closed_at timestamptz,
  status text not null default 'OPEN' check (status in ('OPEN', 'CLOSED', 'CANCELED', 'REJECTED')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Legacy DBs: add missing columns
alter table public.trades add column if not exists signal_id uuid;
alter table public.trades add column if not exists bot_id uuid;
alter table public.trades add column if not exists versao_id uuid;
alter table public.trades add column if not exists exchange_order_id text;
alter table public.trades add column if not exists quantity numeric(20, 8);
alter table public.trades add column if not exists notional_usd numeric(20, 2);
alter table public.trades add column if not exists fee_usd numeric(20, 4);
alter table public.trades add column if not exists exit_price numeric(20, 8);
alter table public.trades add column if not exists pnl_usd numeric(20, 2);
alter table public.trades add column if not exists opened_at timestamptz;
alter table public.trades add column if not exists closed_at timestamptz;
alter table public.trades add column if not exists status text;

-- Default status for legacy rows
update public.trades set status = 'OPEN' where status is null;
alter table public.trades alter column status set default 'OPEN';

create unique index if not exists uniq_trades_signal_id
  on public.trades (signal_id)
  where signal_id is not null;

drop trigger if exists set_trades_updated_at on public.trades;
create trigger set_trades_updated_at
  before update on public.trades
  for each row execute function public.set_updated_at();

drop trigger if exists set_bot_heartbeats_updated_at on public.bot_heartbeats;
create trigger set_bot_heartbeats_updated_at
  before update on public.bot_heartbeats
  for each row execute function public.set_updated_at();

drop trigger if exists set_bots_updated_at on public.bots;
create trigger set_bots_updated_at
  before update on public.bots
  for each row execute function public.set_updated_at();

alter table public.bots enable row level security;
alter table public.bot_heartbeats enable row level security;
alter table public.trades enable row level security;

do $$ begin
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'bots' and policyname = 'bots_anon_all'
  ) then
    create policy "bots_anon_all" on public.bots
      for all
      to anon, authenticated
      using (true)
      with check (true);
  end if;
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'bot_heartbeats' and policyname = 'bot_heartbeats_anon_all'
  ) then
    create policy "bot_heartbeats_anon_all" on public.bot_heartbeats
      for all
      to anon, authenticated
      using (true)
      with check (true);
  end if;
  if not exists (
    select 1 from pg_policies where schemaname = 'public' and tablename = 'trades' and policyname = 'trades_anon_all'
  ) then
    create policy "trades_anon_all" on public.trades
      for all
      to anon, authenticated
      using (true)
      with check (true);
  end if;
end $$;

comment on table public.bots is 'Hub + workers; pair CCXT; params JSON (e.g. max_trade_mins) for strategy.';
