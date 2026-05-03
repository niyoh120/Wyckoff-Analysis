export const PROVIDERS = [
  '1route', 'gemini', 'openai', 'zhipu', 'minimax', 'deepseek', 'qwen', 'volcengine',
] as const

export type Provider = (typeof PROVIDERS)[number]

export const PROVIDER_LABELS: Record<Provider, string> = {
  '1route': '1Route（推荐）',
  gemini: 'Gemini',
  openai: 'OpenAI',
  zhipu: '智谱',
  minimax: 'MiniMax',
  deepseek: 'DeepSeek',
  qwen: '通义千问',
  volcengine: '火山引擎',
}

export const PROVIDER_BASE_URLS: Record<Provider, string> = {
  '1route': 'https://www.1route.dev/v1',
  gemini: '',
  openai: 'https://api.openai.com/v1',
  zhipu: 'https://open.bigmodel.cn/api/paas/v4',
  minimax: 'https://api.minimax.chat/v1',
  deepseek: 'https://api.deepseek.com/v1',
  qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  volcengine: 'https://ark.cn-beijing.volces.com/api/v3',
}

export const TABLE_NAMES = {
  USER_SETTINGS: 'user_settings',
  PORTFOLIOS: 'portfolios',
  PORTFOLIO_POSITIONS: 'portfolio_positions',
  TRADE_ORDERS: 'trade_orders',
  RECOMMENDATION_TRACKING: 'recommendation_tracking',
  TAIL_BUY_HISTORY: 'tail_buy_history',
} as const
