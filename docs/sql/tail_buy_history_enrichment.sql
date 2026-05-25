alter table public.tail_buy_history
  add column if not exists status text default '',
  add column if not exists rule_decision text default '',
  add column if not exists llm_confidence double precision,
  add column if not exists llm_model_used text default '',
  add column if not exists initial_price double precision default 0,
  add column if not exists current_price double precision default 0,
  add column if not exists change_pct double precision default 0,
  add column if not exists price_updated_at timestamptz,
  add column if not exists last_close double precision default 0,
  add column if not exists vwap double precision default 0,
  add column if not exists dist_vwap_pct double precision default 0,
  add column if not exists close_pos double precision default 0,
  add column if not exists day_ret_pct double precision default 0,
  add column if not exists last30_ret_pct double precision default 0,
  add column if not exists last15_ret_pct double precision default 0,
  add column if not exists tail30_volume_share double precision default 0,
  add column if not exists drop_from_high_pct double precision default 0,
  add column if not exists fetch_error text default '',
  add column if not exists features_json jsonb default '{}'::jsonb;

comment on column public.tail_buy_history.initial_price is 'Real stock price captured when the tail-buy row is written.';
comment on column public.tail_buy_history.current_price is 'Latest stock price refreshed by the recommendation reprice schedule.';
comment on column public.tail_buy_history.change_pct is 'Current price change versus initial_price in percent.';
comment on column public.tail_buy_history.price_updated_at is 'Timestamp of the latest tail-buy current_price refresh.';
comment on column public.tail_buy_history.last_close is 'Tail-buy scan last 1m close at decision time.';
comment on column public.tail_buy_history.vwap is 'Intraday VWAP inferred from 1m amount/volume.';
comment on column public.tail_buy_history.dist_vwap_pct is 'Last close distance to VWAP in percent.';
comment on column public.tail_buy_history.close_pos is 'Last close position inside intraday high-low range, 0-1.';
comment on column public.tail_buy_history.features_json is 'Full tail-buy feature snapshot for later review.';
