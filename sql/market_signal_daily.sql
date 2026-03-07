create table if not exists public.market_signal_daily (
  trade_date date primary key,

  benchmark_regime text check (
    benchmark_regime in ('UNKNOWN','RISK_ON','NEUTRAL','RISK_OFF','CRASH','BLACK_SWAN')
  ),
  main_index_code text not null default '000001',
  main_index_close numeric(14,4),
  main_index_ma50 numeric(14,4),
  main_index_ma200 numeric(14,4),
  main_index_recent3_cum_pct numeric(12,6),
  main_index_today_pct numeric(12,6),

  smallcap_index_code text,
  smallcap_close numeric(14,4),
  smallcap_recent3_cum_pct numeric(12,6),

  a50_value_date date,
  a50_source text,
  a50_close numeric(14,4),
  a50_pct_chg numeric(12,6),

  vix_value_date date,
  vix_source text,
  vix_close numeric(14,4),
  vix_pct_chg numeric(12,6),

  premarket_regime text check (
    premarket_regime in ('NORMAL','RISK_OFF','BLACK_SWAN')
  ),
  premarket_reasons jsonb not null default '[]'::jsonb,

  banner_tone text not null default '谨慎' check (
    banner_tone in ('恶劣','保守','谨慎','谨慎乐观','乐观')
  ),
  banner_title text,
  banner_message text,

  source_jobs jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_market_signal_daily_trade_date_desc
  on public.market_signal_daily (trade_date desc);

create or replace function public.market_signal_daily_set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_market_signal_daily_updated_at on public.market_signal_daily;

create trigger trg_market_signal_daily_updated_at
before update on public.market_signal_daily
for each row
execute function public.market_signal_daily_set_updated_at();

alter table public.market_signal_daily enable row level security;

drop policy if exists market_signal_daily_select_authenticated on public.market_signal_daily;

create policy market_signal_daily_select_authenticated
on public.market_signal_daily
for select
to authenticated
using (true);

insert into public.market_signal_daily (
  trade_date,

  benchmark_regime,
  main_index_code,
  main_index_close,
  main_index_ma50,
  main_index_ma200,
  main_index_recent3_cum_pct,
  main_index_today_pct,

  smallcap_index_code,
  smallcap_close,
  smallcap_recent3_cum_pct,

  a50_value_date,
  a50_source,
  a50_close,
  a50_pct_chg,

  vix_value_date,
  vix_source,
  vix_close,
  vix_pct_chg,

  premarket_regime,
  premarket_reasons,

  banner_tone,
  banner_title,
  banner_message,
  source_jobs
) values (
  '2026-03-06',

  'RISK_ON',
  '000001',
  4124.1940,
  4074.0644,
  3791.5126,
  0.036866,
  0.380400,

  '399006',
  3229.3015,
  0.617545,

  '2026-03-07',
  'akshare:futures_global_spot_em(CN00Y)',
  14486.0000,
  -0.920000,

  '2026-03-06',
  'cboe:VIX_History.csv',
  29.4900,
  24.168421,

  'BLACK_SWAN',
  '["VIX涨幅 24.17% >= 15.00%"]'::jsonb,

  '保守',
  '亲爱的投资者，最新交易日的大盘偏强，但盘前风险已显著抬升。',
  '最新交易日（2026-03-06）的大盘水温为 RISK_ON；A50 最新 14486.00（-0.92%），VIX 29.49（+24.17%）。市场当前更适合保守应对，既要乘风而上，也要顺水推舟。',
  '{"seed":"manual_sql_2026-03-07"}'::jsonb
)
on conflict (trade_date) do update
set
  benchmark_regime = excluded.benchmark_regime,
  main_index_code = excluded.main_index_code,
  main_index_close = excluded.main_index_close,
  main_index_ma50 = excluded.main_index_ma50,
  main_index_ma200 = excluded.main_index_ma200,
  main_index_recent3_cum_pct = excluded.main_index_recent3_cum_pct,
  main_index_today_pct = excluded.main_index_today_pct,
  smallcap_index_code = excluded.smallcap_index_code,
  smallcap_close = excluded.smallcap_close,
  smallcap_recent3_cum_pct = excluded.smallcap_recent3_cum_pct,
  a50_value_date = excluded.a50_value_date,
  a50_source = excluded.a50_source,
  a50_close = excluded.a50_close,
  a50_pct_chg = excluded.a50_pct_chg,
  vix_value_date = excluded.vix_value_date,
  vix_source = excluded.vix_source,
  vix_close = excluded.vix_close,
  vix_pct_chg = excluded.vix_pct_chg,
  premarket_regime = excluded.premarket_regime,
  premarket_reasons = excluded.premarket_reasons,
  banner_tone = excluded.banner_tone,
  banner_title = excluded.banner_title,
  banner_message = excluded.banner_message,
  source_jobs = public.market_signal_daily.source_jobs || excluded.source_jobs,
  updated_at = now();
