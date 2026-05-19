export const PROVIDERS = [
  '1route', 'gemini', 'openai', 'deepseek', 'anthropic',
] as const

export type Provider = (typeof PROVIDERS)[number]

export const PROVIDER_LABELS: Record<Provider, string> = {
  '1route': '1Route（推荐）',
  gemini: 'Gemini',
  openai: '兼容OpenAI协议',
  deepseek: 'DeepSeek',
  anthropic: '兼容Anthropic协议',
}

export const PROVIDER_BASE_URLS: Record<Provider, string> = {
  '1route': 'https://www.1route.dev/v1',
  gemini: '',
  openai: 'https://api.openai.com/v1',
  deepseek: 'https://api.deepseek.com/v1',
  anthropic: '',
}

export const TABLE_NAMES = {
  USER_SETTINGS: 'user_settings',
  PORTFOLIOS: 'portfolios',
  PORTFOLIO_POSITIONS: 'portfolio_positions',
  TRADE_ORDERS: 'trade_orders',
  RECOMMENDATION_TRACKING: 'recommendation_tracking',
  TAIL_BUY_HISTORY: 'tail_buy_history',
} as const
