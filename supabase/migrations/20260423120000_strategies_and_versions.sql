-- Strategies + per-strategy versioned code (RLS: owner only)

create extension if not exists "pgcrypto";

-- Status for a version row
do $$ begin
  create type public.strategy_version_status as enum (
    'draft',
    'active',
    'archived'
  );
exception
  when duplicate_object then null;
end $$;

-- Top-level strategy (owned by auth user)
create table if not exists public.strategies (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  name text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Version under a strategy: monotonic int per strategy, code body, status
create table if not exists public.strategy_versions (
  id uuid primary key default gen_random_uuid(),
  strategy_id uuid not null references public.strategies (id) on delete cascade,
  version_number integer not null,
  content text not null default '',
  status public.strategy_version_status not null default 'draft',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint strategy_versions_version_positive check (version_number > 0),
  constraint strategy_versions_unique_per_strategy unique (strategy_id, version_number)
);

create index if not exists idx_strategies_user_id on public.strategies (user_id);
create index if not exists idx_strategy_versions_strategy_id
  on public.strategy_versions (strategy_id);

-- updated_at
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_strategies_updated_at on public.strategies;
create trigger set_strategies_updated_at
  before update on public.strategies
  for each row execute function public.set_updated_at();

drop trigger if exists set_strategy_versions_updated_at on public.strategy_versions;
create trigger set_strategy_versions_updated_at
  before update on public.strategy_versions
  for each row execute function public.set_updated_at();

-- RLS
alter table public.strategies enable row level security;
alter table public.strategy_versions enable row level security;

-- strategies policies
create policy "strategies_select_own"
  on public.strategies for select
  using (auth.uid() = user_id);

create policy "strategies_insert_own"
  on public.strategies for insert
  with check (auth.uid() = user_id);

create policy "strategies_update_own"
  on public.strategies for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "strategies_delete_own"
  on public.strategies for delete
  using (auth.uid() = user_id);

-- strategy_versions: same owner as parent strategy
create policy "strategy_versions_select_via_strategy"
  on public.strategy_versions for select
  using (
    exists (
      select 1
      from public.strategies s
      where s.id = strategy_id
        and s.user_id = auth.uid()
    )
  );

create policy "strategy_versions_insert_via_strategy"
  on public.strategy_versions for insert
  with check (
    exists (
      select 1
      from public.strategies s
      where s.id = strategy_id
        and s.user_id = auth.uid()
    )
  );

create policy "strategy_versions_update_via_strategy"
  on public.strategy_versions for update
  using (
    exists (
      select 1
      from public.strategies s
      where s.id = strategy_id
        and s.user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1
      from public.strategies s
      where s.id = strategy_id
        and s.user_id = auth.uid()
    )
  );

create policy "strategy_versions_delete_via_strategy"
  on public.strategy_versions for delete
  using (
    exists (
      select 1
      from public.strategies s
      where s.id = strategy_id
        and s.user_id = auth.uid()
    )
  );

-- Optional: help PostgREST ordering
comment on table public.strategies is 'User trading strategies';
comment on table public.strategy_versions is 'Versioned python (or other) code per strategy';
