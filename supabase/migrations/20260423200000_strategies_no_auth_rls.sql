-- No-login app: allow anon read/write, optional legacy user_id

drop policy if exists "strategies_select_own" on public.strategies;
drop policy if exists "strategies_insert_own" on public.strategies;
drop policy if exists "strategies_update_own" on public.strategies;
drop policy if exists "strategies_delete_own" on public.strategies;

drop policy if exists "strategy_versions_select_via_strategy" on public.strategy_versions;
drop policy if exists "strategy_versions_insert_via_strategy" on public.strategy_versions;
drop policy if exists "strategy_versions_update_via_strategy" on public.strategy_versions;
drop policy if exists "strategy_versions_delete_via_strategy" on public.strategy_versions;

alter table public.strategies drop constraint if exists strategies_user_id_fkey;
alter table public.strategies alter column user_id drop not null;

-- Open RLS: anon + authenticated (anon key only) — not for untrusted public apps
create policy "strategies_anon_all"
  on public.strategies
  for all
  to anon, authenticated
  using (true)
  with check (true);

create policy "strategy_versions_anon_all"
  on public.strategy_versions
  for all
  to anon, authenticated
  using (true)
  with check (true);
