begin;

alter table public.recommendation_tracking
  add column if not exists strategy_version text default '',
  add column if not exists candidate_lane text default '',
  add column if not exists entry_type text default '',
  add column if not exists signal_key text default '',
  add column if not exists candidate_status text default '',
  add column if not exists candidate_timing text default '',
  add column if not exists candidate_risk text default '',
  add column if not exists candidate_reasons jsonb default '{}'::jsonb,
  add column if not exists candidate_metrics jsonb default '{}'::jsonb,
  add column if not exists mainline_score double precision,
  add column if not exists theme_score double precision,
  add column if not exists stock_role_score double precision,
  add column if not exists quality_score double precision,
  add column if not exists timing_score double precision;

alter table public.signal_pending
  add column if not exists strategy_version text default '',
  add column if not exists candidate_lane text default '',
  add column if not exists entry_type text default '',
  add column if not exists signal_key text default '',
  add column if not exists candidate_status text default '',
  add column if not exists candidate_timing text default '',
  add column if not exists candidate_risk text default '',
  add column if not exists candidate_reasons jsonb default '{}'::jsonb,
  add column if not exists candidate_metrics jsonb default '{}'::jsonb,
  add column if not exists mainline_score double precision,
  add column if not exists theme_score double precision,
  add column if not exists stock_role_score double precision,
  add column if not exists quality_score double precision,
  add column if not exists timing_score double precision;

alter table public.signal_observations
  add column if not exists strategy_version text default '',
  add column if not exists candidate_lane text default '',
  add column if not exists entry_type text default '',
  add column if not exists signal_key text default '',
  add column if not exists candidate_status text default '';

create index if not exists idx_recommendation_tracking_strategy_version
  on public.recommendation_tracking(strategy_version);
create index if not exists idx_recommendation_tracking_candidate_lane
  on public.recommendation_tracking(candidate_lane);
create index if not exists idx_signal_pending_strategy_version
  on public.signal_pending(strategy_version);
create index if not exists idx_signal_pending_candidate_lane
  on public.signal_pending(candidate_lane);
create index if not exists idx_signal_observations_strategy_version
  on public.signal_observations(strategy_version);
create index if not exists idx_signal_observations_candidate_lane
  on public.signal_observations(candidate_lane);

update public.recommendation_tracking
set strategy_version = 'pre_lane_v1'
where coalesce(strategy_version, '') = '';

update public.signal_pending
set strategy_version = 'pre_lane_v1'
where coalesce(strategy_version, '') = '';

update public.signal_observations
set strategy_version = 'pre_lane_v1'
where coalesce(strategy_version, '') = '';

comment on column public.recommendation_tracking.strategy_version is 'Funnel strategy generation marker. pre_lane_v1 is historical data; lane_v2 is the mainline/candidate-lane funnel.';
comment on column public.recommendation_tracking.candidate_lane is 'Candidate source lane such as mainline, trend_pullback, sector_strength, or wyckoff_structure.';
comment on column public.recommendation_tracking.entry_type is 'Trade setup label used by the candidate lane or mainline engine.';
comment on column public.recommendation_tracking.candidate_metrics is 'Structured candidate-lane metrics snapshot for later attribution.';
comment on column public.signal_pending.candidate_lane is 'Candidate source lane for second confirmation and tail-buy jobs.';
comment on column public.signal_observations.candidate_lane is 'Candidate source lane index; detailed metadata lives in features_json.candidate_metadata.';

commit;
