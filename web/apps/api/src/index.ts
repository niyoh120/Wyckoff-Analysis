import { Hono } from 'hono'
import { cors } from 'hono/cors'
import { chatRoutes } from './routes/chat'
import { portfolioRoutes } from './routes/portfolio'
import { settingsRoutes } from './routes/settings'

export type Env = {
  SUPABASE_URL: string
  SUPABASE_ANON_KEY: string
  SUPABASE_SERVICE_ROLE_KEY: string
  TICKFLOW_API_BASE: string
}

const app = new Hono<{ Bindings: Env }>()

app.use('*', cors({
  origin: ['http://localhost:5173', 'https://wyckoff.pages.dev'],
  credentials: true,
}))

app.get('/api/health', (c) => c.json({ status: 'ok' }))

app.route('/api/chat', chatRoutes)
app.route('/api/portfolio', portfolioRoutes)
app.route('/api/settings', settingsRoutes)

export default app
