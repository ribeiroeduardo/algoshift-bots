-- Merge strategy_versions into bots: code lives on each bot row; drop strategy_versions.

alter table public.bots
  add column if not exists content text not null default '',
  add column if not exists version_number integer,
  add column if not exists code_status public.strategy_version_status not null default 'draft';

-- Backfill from linked strategy_version row
update public.bots b
set
  content = sv.content,
  version_number = sv.version_number,
  code_status = sv.status
from public.strategy_versions sv
where b.active_version_id is not null
  and sv.id = b.active_version_id;

-- Remaining bots: copy code from latest strategy_version (do not set version_number yet — avoids dupes)
update public.bots b
set
  content = sv.content,
  code_status = sv.status
from (
  select distinct on (strategy_id)
    strategy_id,
    content,
    status
  from public.strategy_versions
  order by strategy_id, version_number desc
) sv
where b.strategy_id = sv.strategy_id
  and (b.content is null or b.content = '');

-- Sequential version_number 1..n per strategy (replaces any prior numbers)
with ordered as (
  select
    id,
    row_number() over (partition by strategy_id order by created_at, id) as rn
  from public.bots
)
update public.bots b
set version_number = o.rn
from ordered o
where b.id = o.id;

alter table public.bots alter column version_number set not null;

alter table public.bots drop constraint if exists bots_strategy_version_unique;
alter table public.bots add constraint bots_strategy_version_unique unique (strategy_id, version_number);

create index if not exists idx_bots_strategy_version on public.bots (strategy_id, version_number);

-- trades.versao_id: keep column, drop FK to dropped table (stores bot_id for new rows)
alter table public.trades drop constraint if exists trades_versao_id_fkey;

update public.trades
set versao_id = bot_id
where versao_id is not null and bot_id is not null and versao_id <> bot_id;

alter table public.bots drop constraint if exists bots_active_version_id_fkey;
alter table public.bots drop column if exists active_version_id;

drop policy if exists "strategy_versions_anon_all" on public.strategy_versions;
drop table if exists public.strategy_versions cascade;

comment on column public.bots.content is 'Python strategy code for this bot.';
comment on column public.bots.version_number is 'Monotonic index per strategy_id (display + uniqueness).';
comment on column public.bots.code_status is 'draft | active | archived (code lifecycle, independent of bot runtime status).';
