begin;

create table if not exists public.external_seed_observations (
  id bigserial primary key,
  market text not null default 'cn',
  trade_date date not null,
  source text not null default 'external',
  source_rank integer,
  code text not null,
  name text not null default '',
  industry text not null default '',
  passed_l1 boolean not null default false,
  passed_l2 boolean not null default false,
  l4_confirmed boolean not null default false,
  l4_trigger_tags text[] not null default '{}',
  watch_status text not null default 'WATCH',
  expires_at date not null,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (market, trade_date, source, code)
);

create index if not exists external_seed_observations_trade_date_idx
on public.external_seed_observations (market, trade_date desc);

create index if not exists external_seed_observations_expires_at_idx
on public.external_seed_observations (expires_at);

comment on table public.external_seed_observations is
'Shadow-only external candidate seed observations. Rows are written by server jobs and expire via expires_at plus db_maintenance retention.';

comment on column public.external_seed_observations.expires_at is
'Candidate watch expiry date. Server maintenance also deletes rows older than FUNNEL_EXTERNAL_SEED_RETENTION_DAYS, default 180 days.';

alter table public.external_seed_observations enable row level security;

revoke all on table public.external_seed_observations from anon, authenticated;
grant select on table public.external_seed_observations to authenticated;

drop policy if exists external_seed_observations_whitelist_select
on public.external_seed_observations;

create policy external_seed_observations_whitelist_select
on public.external_seed_observations
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
