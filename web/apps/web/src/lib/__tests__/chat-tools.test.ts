import { describe, it, expect, vi } from 'vitest'
import type { ToolDeps, KlineRow } from '@wyckoff/shared'
import {
  buildValueAgentDigest,
  buildKlineDigest,
  execSearchStock,
  execViewPortfolio,
  execMarketOverview,
  execQueryRecommendations,
  execQueryAttribution,
  execQueryTailBuy,
  execExecutePortfolioUpdate,
  execScreenStocks,
  execAnalyzeStock,
  execMarketHistory,
} from '@wyckoff/shared'

function createMockChain(resolvedData: unknown = null, error: unknown = null) {
  const chain: Record<string, unknown> = {}
  const terminal = () => Promise.resolve({ data: resolvedData, error })
  for (const method of ['select', 'eq', 'ilike', 'in', 'order', 'limit', 'delete', 'update']) {
    chain[method] = vi.fn().mockReturnValue(chain)
  }
  chain['insert'] = vi.fn().mockImplementation(terminal)
  chain['single'] = vi.fn().mockImplementation(terminal)
  chain['upsert'] = vi.fn().mockImplementation(terminal)
  // make the chain itself thenable for queries without .single()
  chain['then'] = (resolve: (v: unknown) => void) => resolve({ data: resolvedData, error })
  return chain
}

function createPortfolioWriteDeps(updateRows: unknown[]) {
  const updateChain = createMockChain(updateRows)
  const insertChain = createMockChain(null)
  const mockFrom = vi.fn()
    .mockReturnValueOnce(updateChain)
    .mockReturnValueOnce(insertChain)
  const deps = {
    supabase: { from: mockFrom } as unknown as ToolDeps['supabase'],
    fetch: vi.fn(),
    generateText: vi.fn(),
  } as unknown as ToolDeps
  return { deps, updateChain, insertChain }
}

function createMockDeps(tableData: Record<string, unknown> = {}): ToolDeps {
  const mockFrom = vi.fn().mockImplementation((table: string) => {
    const data = tableData[table] ?? null
    return createMockChain(data)
  })

  return {
    supabase: { from: mockFrom } as unknown as ToolDeps['supabase'],
    fetch: vi.fn().mockResolvedValue({ ok: false, json: () => Promise.resolve({}) } as Response),
    generateText: vi.fn().mockResolvedValue({ text: 'mocked LLM response' }),
  }
}

function makeKlineRows(n: number, base = 10): KlineRow[] {
  return Array.from({ length: n }, (_, i) => ({
    date: `2024-01-${String(i + 1).padStart(2, '0')}`,
    open: base + i * 0.1,
    high: base + i * 0.1 + 0.5,
    low: base + i * 0.1 - 0.3,
    close: base + i * 0.12,
    volume: 100000 + i * 1000,
  }))
}

describe('buildKlineDigest', () => {
  it('returns placeholder for empty data', () => {
    expect(buildKlineDigest([])).toBe('无可用K线数据')
  })

  it('produces stable output for 5 rows', () => {
    const rows = makeKlineRows(5)
    expect(buildKlineDigest(rows)).toMatchSnapshot()
  })

  it('produces stable output for 20 rows', () => {
    const rows = makeKlineRows(20)
    expect(buildKlineDigest(rows)).toMatchSnapshot()
  })

  it('includes MA50 for 50+ rows', () => {
    const rows = makeKlineRows(60)
    const result = buildKlineDigest(rows)
    expect(result).toContain('MA50=')
  })

  it('includes MA120 for 120+ rows', () => {
    const rows = makeKlineRows(130)
    const result = buildKlineDigest(rows)
    expect(result).toContain('MA120=')
  })
})

describe('buildValueAgentDigest', () => {
  it('adds score signals to the compact value prompt', () => {
    const digest = buildValueAgentDigest({
      symbol: '600519.SH',
      source: 'tickflow',
      metrics: {
        period_end: '2026-03-31',
        roe: 18.2,
        net_income_yoy: 11.8,
        revenue_yoy: 6.5,
        gross_margin: 91.6,
        debt_to_asset_ratio: 21.4,
        operating_cash_to_revenue: 16.2,
      },
    })

    expect(digest).toContain('价值面摘要（来源：TickFlow，报告期：2026-03-31）')
    expect(digest).toContain('ROE=18.20%')
    expect(digest).toContain('价值面评级：稳健')
    expect(digest).toContain('质量信号：')
  })
})

describe('execSearchStock', () => {
  it('returns not-found message when no results', async () => {
    const deps = createMockDeps({
      recommendation_tracking: [],
      portfolio_positions: [],
      tail_buy_history: [],
    })
    const result = await execSearchStock(deps, 'user1', '999999')
    expect(result).toContain('未找到匹配')
  })

  it('returns formatted stock list with code and name', async () => {
    const stocks = [{ code: 600519, name: '贵州茅台' }]
    const deps = createMockDeps({
      recommendation_tracking: stocks,
      portfolio_positions: [],
      tail_buy_history: [],
    })
    const result = await execSearchStock(deps, 'user1', '贵州')
    expect(result).toContain('600519')
    expect(result).toContain('贵州茅台')
  })
})

describe('execViewPortfolio', () => {
  it('returns empty portfolio message', async () => {
    const deps = createMockDeps({
      portfolios: { free_cash: 50000 },
      portfolio_positions: [],
    })
    const result = await execViewPortfolio(deps, 'user1')
    expect(result).toContain('当前无持仓')
    expect(result).toContain('50,000')
  })

  it('returns formatted positions', async () => {
    const deps = createMockDeps({
      portfolios: { free_cash: 10000 },
      portfolio_positions: [
        { code: '000001', name: '平安银行', shares: 1000, cost_price: 12.5, buy_dt: '2024-01-01', stop_loss: 11.0 },
      ],
    })
    const result = await execViewPortfolio(deps, 'user1')
    expect(result).toContain('持仓 1 只')
    expect(result).toContain('平安银行')
    expect(result).toContain('1000股')
  })
})

describe('execMarketOverview', () => {
  it('returns no-data message when empty', async () => {
    const deps = createMockDeps({ market_signal_daily: [] })
    const result = await execMarketOverview(deps)
    expect(result).toBe('暂无最新市场信号数据')
  })

  it('returns formatted market data', async () => {
    const deps = createMockDeps({
      market_signal_daily: [
        { benchmark_regime: 'RISK_ON', main_index_close: 3200, main_index_today_pct: 1.5, a50_close: 14000, a50_pct_chg: 0.8, vix_close: 15.2 },
      ],
    })
    const result = await execMarketOverview(deps)
    expect(result).toContain('偏强')
    expect(result).toContain('3200')
  })
})

describe('execMarketHistory', () => {
  it('uses TickFlow index K-line history for historical market questions', async () => {
    const deps = createMockDeps({ user_settings: { tickflow_api_key: ' tf-test ', tushare_token: '' } })
    deps.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        data: {
          '000001.SH': {
            timestamp: [1704067200000, 1704153600000, 1704240000000],
            open: [3000, 3010, 3020],
            high: [3030, 3040, 3050],
            low: [2990, 3000, 3010],
            close: [3020, 3030, 3040],
            volume: [1000, 1200, 1300],
          },
        },
      }),
    } as Response) as unknown as ToolDeps['fetch']

    const result = await execMarketHistory(deps, 'user1', {}, 100, 'sse')

    expect(result).toBe('mocked LLM response')
    expect(deps.fetch).toHaveBeenCalledWith(
      expect.stringContaining('symbol=000001.SH'),
      expect.objectContaining({ headers: expect.objectContaining({ 'x-api-key': 'tf-test' }) }),
    )
    expect(deps.generateText).toHaveBeenCalledWith(expect.objectContaining({
      prompt: expect.stringContaining('最近3个交易日'),
    }))
  })

  it('explains missing TickFlow key', async () => {
    const deps = createMockDeps({ user_settings: { tickflow_api_key: '', tushare_token: '' } })

    const result = await execMarketHistory(deps, 'user1', {}, 100, 'sse')

    expect(result).toContain('配置 TickFlow API Key')
    expect(deps.fetch).not.toHaveBeenCalled()
  })
})

describe('execQueryRecommendations', () => {
  it('returns no-data message when empty', async () => {
    const deps = createMockDeps({ recommendation_tracking: [] })
    const result = await execQueryRecommendations(deps, 10)
    expect(result).toBe('暂无形态复盘记录')
  })

  it('formats recommendation entries', async () => {
    const deps = createMockDeps({
      recommendation_tracking: [
        { code: 600519, name: '贵州茅台', recommend_date: 20240101, recommend_count: 3, initial_price: 1800, current_price: 1900, change_pct: 5.56, is_ai_recommended: true },
        { code: 603039, name: '泛微网络', recommend_date: 20240615, recommend_count: 1, initial_price: 46.97, current_price: 44.2, change_pct: -5.9, is_ai_recommended: false },
      ],
      signal_pending: [],
    })
    const result = await execQueryRecommendations(deps, 10)
    expect(result).toContain('600519')
    expect(result).toContain('AI推荐')
    expect(result).toContain('观察/信号复盘')
    expect(result).toContain('入选3次')
    expect(result).toContain('+5.56%')
    expect(result).toContain('-5.90%')
    expect(result).toContain('观察/信号复盘不等于买入')
  })

  it('includes signal_pending entries as pending signals', async () => {
    const deps = createMockDeps({
      recommendation_tracking: [],
      signal_pending: [
        { code: '002079', name: '苏州固锝', signal_date: '2026-06-30', status: 'pending', signal_type: 'lps', signal_score: 0.56, snap_close: 12.3 },
        { code: '603661', name: '恒林股份', signal_date: '2026-06-29', status: 'confirmed', signal_type: 'sos', signal_score: 0.9, snap_close: 33.2 },
      ],
    })
    const result = await execQueryRecommendations(deps, 10)
    expect(result).toContain('002079')
    expect(result).toContain('待确认信号')
    expect(result).toContain('603661')
    expect(result).toContain('已确认信号')
    expect(result).toContain('信号日20260630')
  })
})

describe('execQueryTailBuy', () => {
  it('returns no-data message when empty', async () => {
    const deps = createMockDeps({ tail_buy_history: [] })
    const result = await execQueryTailBuy(deps, 10)
    expect(result).toBe('暂无尾盘买入记录')
  })

  it('surfaces attribution next action in policy weight text', async () => {
    const deps = createMockDeps({
      tail_buy_history: [
        {
          code: '002079',
          name: '苏州固锝',
          run_date: '2026-07-04',
          signal_type: 'lps',
          final_decision: 'WATCH',
          initial_price: 12,
          current_price: 12.5,
          change_pct: 4.2,
          dist_vwap_pct: 1.1,
          rule_score: 40,
          llm_decision: '',
          llm_reason: '',
          features_json: {
            policy_weight_signal: 'lps',
            policy_weight_multiplier: 0.5,
            policy_weight_old_score: 80,
            policy_weight_new_score: 40,
            policy_weight_source: '远端',
            policy_weight_report_date: '2026-07-04',
            policy_weight_horizon: '5',
            policy_weight_execution_policy: 'shadow',
            policy_weight_execution_scope: 'tail_buy_and_funnel_shadow',
            policy_weight_next_action: 'manual_review_dynamic_on',
          },
        },
      ],
    })

    const result = await execQueryTailBuy(deps, 10)

    expect(result).toContain('归因调权 lps x0.50 80.0→40.0')
    expect(result).toContain('next=manual_review_dynamic_on')
  })
})

describe('execQueryAttribution', () => {
  it('returns no-data message when empty', async () => {
    const deps = createMockDeps({ strategy_attribution_reports: [] })
    const result = await execQueryAttribution(deps, 1)
    expect(result).toContain('暂无策略归因报告')
    expect(result).toContain('Web 只读取远端 strategy_attribution_reports')
    expect(result).toContain('query_history(source="attribution")')
  })

  it('formats execution state, latest shadow, and scoped actions', async () => {
    const deps = createMockDeps({
      strategy_attribution_reports: [
        {
          report_date: '2026-07-04',
          window_start: '2026-05-05',
          window_end: '2026-07-04',
          shadow_diff_stats_json: {
            policy_governor: {
              status: 'candidate',
              mode_recommendation: 'review_promote_dynamic_policy',
              next_action: 'manual_review_dynamic_on',
              next_action_summary: 'shadow 新增组已跑赢移除组；先完成晋级清单和回测复核，再人工决定 dynamic=on。',
              promotion_status: 'manual_review_required',
              promotion_checklist: [
                { key: 'shadow_sample', status: 'pass', summary: 'sample ok' },
                { key: 'backtest_confirmation', status: 'review', summary: 'need backtest' },
              ],
              auto_apply: false,
              summary: 'shadow 新增组显著优于移除组',
            },
            policy_execution_state: {
              funnel_dynamic_policy: 'shadow',
              horizon: '5',
              scope: 'tail_buy_and_funnel_shadow',
              next_action: 'manual_review_dynamic_on',
              next_action_summary: 'shadow 新增组已跑赢移除组；先完成晋级清单和回测复核，再人工决定 dynamic=on。',
              promotion_status: 'manual_review_required',
              promotion_checklist: [
                { key: 'shadow_sample', status: 'pass', summary: 'sample ok' },
                { key: 'backtest_confirmation', status: 'review', summary: 'need backtest' },
              ],
              signal_action_count: 1,
              summary: 'h=5 调权会影响尾盘和漏斗 shadow。',
            },
            latest: {
              trade_date: '2026-07-03',
              regime: 'RISK_ON',
              selection_summary: {
                base_count: 8,
                shadow_count: 9,
                diff_added_count: 2,
                diff_removed_count: 1,
                jaccard: 0.7,
              },
              diff_added_sample: ['300502', '688008'],
              diff_removed_sample: ['002079'],
            },
          },
          recommendations_json: [
            {
              type: 'downweight',
              horizon: '5',
              target: 'lps',
              reason: {
                weight_multiplier: 0.5,
                scope: { regime: 'RISK_ON', lane: 'trend_pullback' },
                evidence: { avg_return_pct: -3.0, win_rate_pct: 39.8, avg_drawdown_pct: -11.15 },
              },
            },
          ],
        },
      ],
    })

    const result = await execQueryAttribution(deps, 1)

    expect(result).toContain('策略归因报告 2026-07-04')
    expect(result).toContain('数据来源：远端 strategy_attribution_reports')
    expect(result).toContain('promotion=manual_review_required')
    expect(result).toContain('晋级检查：shadow_sample:pass；backtest_confirmation:review')
    expect(result).toContain(
      '执行态：mode=shadow | h=5 | scope=tail_buy_and_funnel_shadow | promotion=manual_review_required | next=manual_review_dynamic_on | formal=allowed | actions=1',
    )
    expect(result).toContain('最新 Shadow：2026-07-03 / RISK_ON | base=8 | shadow=9 | 新增=2 | 移除=1 | Jaccard=0.70')
    expect(result).toContain('Shadow 新增样本：300502, 688008')
    expect(result).toContain('lps[regime=RISK_ON, lane=trend_pullback] | downweight | h=5 | x0.50')
    expect(result).toContain('avg=-3')
  })
})

describe('execExecutePortfolioUpdate', () => {
  it('handles delete action', async () => {
    const deps = createMockDeps({ portfolio_positions: null })
    const result = await execExecutePortfolioUpdate(deps, 'user1', 'delete', '600519', '贵州茅台', null, null, null)
    expect(result).toContain('已删除')
    expect(result).toContain('600519')
  })

  it('rejects add without required fields', async () => {
    const deps = createMockDeps({})
    const result = await execExecutePortfolioUpdate(deps, 'user1', 'add', '600519', null, null, null, null)
    expect(result).toContain('执行失败')
  })

  it('handles add action with all fields', async () => {
    const deps = createMockDeps({ portfolio_positions: null })
    const result = await execExecutePortfolioUpdate(deps, 'user1', 'add', '600519', '贵州茅台', 100, 1800, 1700)
    expect(result).toContain('已新增')
    expect(result).toContain('100股')
  })

  it('updates an existing position without inserting a duplicate row', async () => {
    const { deps, updateChain, insertChain } = createPortfolioWriteDeps([{ id: 'pos-1' }])

    const result = await execExecutePortfolioUpdate(deps, 'user1', 'update', '600519', '贵州茅台', 200, 1810, 1700)

    expect(result).toContain('已更新')
    expect(updateChain.update).toHaveBeenCalledWith(expect.objectContaining({ code: '600519', shares: 200 }))
    expect(updateChain.eq).toHaveBeenCalledWith('portfolio_id', 'USER_LIVE:user1')
    expect(updateChain.eq).toHaveBeenCalledWith('code', '600519')
    expect(insertChain.insert).not.toHaveBeenCalled()
  })

  it('inserts a position only when no existing row matches', async () => {
    const { deps, insertChain } = createPortfolioWriteDeps([])

    const result = await execExecutePortfolioUpdate(deps, 'user1', 'add', '600519', '贵州茅台', 100, 1800, 1700)

    expect(result).toContain('已新增')
    expect(insertChain.insert).toHaveBeenCalledWith(expect.objectContaining({ portfolio_id: 'USER_LIVE:user1', code: '600519' }))
  })
})

describe('execScreenStocks', () => {
  it('returns no-data message when empty', async () => {
    const deps = createMockDeps({ recommendation_tracking: [] })
    const result = await execScreenStocks(deps)
    expect(result.stocks).toEqual([])
    expect(result.meta.ai_count).toBe(0)
  })
})

describe('execAnalyzeStock', () => {
  it('includes value snapshot when analyzing A-share stocks', async () => {
    const deps = createMockDeps({ user_settings: { tickflow_api_key: ' tf-test ', tushare_token: '' } })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          data: [
            { date: '2024-01-01', open: 100, high: 103, low: 99, close: 102, volume: 1000 },
            { date: '2024-01-02', open: 102, high: 105, low: 101, close: 104, volume: 1200 },
          ],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          data: {
            '600519.SH': [{
              period_end: '2026-03-31',
              roe: 18.2,
              net_income_yoy: 11.8,
              revenue_yoy: 6.5,
              gross_margin: 91.6,
              net_margin: 48.3,
              debt_to_asset_ratio: 21.4,
              operating_cash_to_revenue: 16.2,
            }],
          },
        }),
      })
    deps.fetch = fetchMock as unknown as ToolDeps['fetch']

    const result = await execAnalyzeStock(
      deps,
      'user1',
      { api_key: 'llm-key', model: 'test-model', base_url: 'https://example.com/v1' },
      {},
      '600519',
      '贵州茅台',
    )

    expect(result.markdown).toBe('mocked LLM response')
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/llm-proxy/v1/financials/metrics?'),
      expect.objectContaining({ headers: expect.objectContaining({ 'x-api-key': 'tf-test' }) }),
    )
    expect(deps.generateText).toHaveBeenCalledWith(expect.objectContaining({
      system: expect.stringContaining('价值面校准'),
      prompt: expect.stringContaining('价值面摘要（来源：TickFlow，报告期：2026-03-31）'),
    }))
    expect(deps.generateText).toHaveBeenCalledWith(expect.objectContaining({
      prompt: expect.stringContaining('K线共2根'),
    }))
  })

  it('uses TickFlow batch fallback for market symbols', async () => {
    const deps = createMockDeps({ user_settings: { tickflow_api_key: ' tf-test ', tushare_token: '' } })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ data: {} }) })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          data: {
            'AAPL.US': {
              timestamp: [1704067200000, 1704153600000],
              open: [100, 101],
              high: [102, 103],
              low: [99, 100],
              close: [101, 102],
              volume: [1000, 1200],
            },
          },
        }),
      })
    deps.fetch = fetchMock as unknown as ToolDeps['fetch']

    const result = await execAnalyzeStock(
      deps,
      'user1',
      { api_key: 'llm-key', model: 'test-model', base_url: 'https://example.com/v1' },
      {},
      'AAPL.US',
      '苹果',
    )

    expect(result.markdown).toBe('mocked LLM response')
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining('/api/llm-proxy/v1/klines/batch?'),
      expect.objectContaining({ headers: expect.objectContaining({ 'x-api-key': 'tf-test' }) }),
    )
  })

  it('explains missing TickFlow key for market symbols', async () => {
    const deps = createMockDeps({ user_settings: { tickflow_api_key: '', tushare_token: '' } })

    const result = await execAnalyzeStock(
      deps,
      'user1',
      { api_key: 'llm-key', model: 'test-model', base_url: 'https://example.com/v1' },
      {},
      'AAPL.US',
      '苹果',
    )

    expect(result.summary).toContain('设置页配置 TickFlow API Key')
    expect(deps.fetch).not.toHaveBeenCalled()
  })
})
