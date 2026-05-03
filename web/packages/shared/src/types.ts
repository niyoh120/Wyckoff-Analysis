export interface UserSettings {
  user_id: string
  chat_provider: string
  gemini_api_key?: string
  gemini_model?: string
  gemini_base_url?: string
  openai_api_key?: string
  openai_model?: string
  openai_base_url?: string
  deepseek_api_key?: string
  deepseek_model?: string
  deepseek_base_url?: string
  custom_providers?: Record<string, { apikey?: string; model?: string; baseurl?: string }>
  feishu_webhook?: string
  wecom_webhook?: string
  dingtalk_webhook?: string
  tushare_token?: string
  tickflow_api_key?: string
  tg_bot_token?: string
  tg_chat_id?: string
}

export interface Position {
  code: string
  name: string
  shares: number
  cost_price: number
  buy_dt?: string
  stop_loss?: number
}

export interface PortfolioState {
  portfolio_id: string
  free_cash: number
  total_equity?: number
  positions: Position[]
  state_updated_at?: string
}

export interface TradeOrder {
  id: string
  run_id: string
  trade_date: string
  model: string
  market_view: string
  code: string
  action: string
  status: string
  shares: number
  price_hint: number
  amount: number
  stop_loss?: number
  reason: string
}
