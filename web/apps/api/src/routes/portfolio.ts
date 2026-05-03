import { Hono } from 'hono'
import { authMiddleware } from '../middleware/auth'
import type { Env } from '../index'

export const portfolioRoutes = new Hono<{ Bindings: Env }>()

portfolioRoutes.use('*', authMiddleware)

portfolioRoutes.get('/', async (c) => {
  // Phase 2: load portfolio from Supabase
  return c.json({ message: 'Portfolio endpoint - Phase 2' })
})
