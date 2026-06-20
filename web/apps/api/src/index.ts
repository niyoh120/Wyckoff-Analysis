import { Hono } from 'hono'
import { cors } from 'hono/cors'
import { chatRoutes } from './routes/chat'
import { portfolioRoutes } from './routes/portfolio'
import { settingsRoutes } from './routes/settings'

export type Env = {
  SUPABASE_URL?: string
  SUPABASE_ANON_KEY?: string
  SUPABASE_SERVICE_ROLE_KEY?: string
  VITE_SUPABASE_URL?: string
  VITE_SUPABASE_ANON_KEY?: string
  TICKFLOW_API_BASE?: string
  CHAT_DAILY_LIMIT_PER_USER?: string
  CHAT_MIN_INTERVAL_MS?: string
  CHAT_TOOL_APPROVAL_SECRET?: string
}

const app = new Hono<{ Bindings: Env }>()

app.use('*', cors({
  origin: [
    'http://localhost:5173',
    'http://localhost:5174',
    'http://localhost:5175',
    'http://127.0.0.1:5173',
    'http://127.0.0.1:5174',
    'http://127.0.0.1:5175',
    'https://wyckoff-analysis.pages.dev',
    'https://wyckoff.pages.dev',
  ],
  credentials: true,
}))

app.get('/api/health', (c) => c.json({ status: 'ok' }))

app.route('/api/chat', chatRoutes)
app.route('/api/portfolio', portfolioRoutes)
app.route('/api/settings', settingsRoutes)

export default app
