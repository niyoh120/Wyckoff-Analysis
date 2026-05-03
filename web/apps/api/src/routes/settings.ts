import { Hono } from 'hono'
import { authMiddleware } from '../middleware/auth'
import type { Env } from '../index'

export const settingsRoutes = new Hono<{ Bindings: Env }>()

settingsRoutes.use('*', authMiddleware)

settingsRoutes.get('/', async (c) => {
  // Phase 2: load user settings
  return c.json({ message: 'Settings endpoint - Phase 2' })
})

settingsRoutes.put('/', async (c) => {
  // Phase 2: save user settings
  return c.json({ message: 'Settings save endpoint - Phase 2' })
})
