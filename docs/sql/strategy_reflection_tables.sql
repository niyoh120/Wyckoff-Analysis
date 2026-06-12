begin;

alter table public.signal_observations
  add column if not exists profile_tag text,
  add column if not exists stage_tag text,
  add column if not exists trigger_tags text[] not null default '{}',
  add column if not exists selection_mode text not null default '',
  add column if not exists policy_version text not null default '',
  add column if not exists candidate_rank integer;

create table if not exists public.strategy_reflections (
  id bigserial primary key,
  market text not null default 'cn',
  as_of_date date not null,
  horizon_days integer not null default 5,
  status text not null default 'SHADOW',
  summary jsonb not null default '{}'::jsonb,
  reflection_text text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (market, as_of_date, horizon_days)
);

create table if not exists public.strategy_policy_candidates (
  id bigserial primary key,
  market text not null default 'cn',
  as_of_date date not null,
  status text not null default 'READY_FOR_REVIEW',
  source_reflection_date date,
  candidate_policy jsonb not null default '{}'::jsonb,
  validation_summary jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (market, as_of_date)
);

alter table public.strategy_reflections enable row level security;
alter table public.strategy_policy_candidates enable row level security;

revoke all on table public.strategy_reflections from anon, authenticated;
revoke all on table public.strategy_policy_candidates from anon, authenticated;

grant select on table public.strategy_reflections to authenticated;
grant select on table public.strategy_policy_candidates to authenticated;

drop policy if exists strategy_reflections_whitelist_select on public.strategy_reflections;
create policy strategy_reflections_whitelist_select
on public.strategy_reflections
for select
to authenticated
using (
  exists (
    select 1
    from public.whitelist w
    where w.user_id = auth.uid()::text
  )
);

drop policy if exists strategy_policy_candidates_whitelist_select on public.strategy_policy_candidates;
create policy strategy_policy_candidates_whitelist_select
on public.strategy_policy_candidates
for select
to authenticated
using (
  exists (
    select 1
    from public.whitelist w
    where w.user_id = auth.uid()::text
  )
);

commit;
