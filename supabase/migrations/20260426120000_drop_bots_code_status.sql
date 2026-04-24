-- Remove duplicate “code lifecycle” (draft/active/archived). Only `public.bots.status` (runtime) remains.
alter table public.bots drop column if exists code_status;

-- Optional: no remaining columns use strategy_version_status after the merge migration dropped strategy_versions.
drop type if exists public.strategy_version_status;
