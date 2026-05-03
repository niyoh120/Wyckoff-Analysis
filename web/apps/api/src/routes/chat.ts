import { Hono } from 'hono'
import { authMiddleware } from '../middleware/auth'
import type { Env } from '../index'

export const chatRoutes = new Hono<{ Bindings: Env }>()

chatRoutes.use('*', authMiddleware)

chatRoutes.post('/', async (c) => {
  // Phase 3: Vercel AI SDK streamText + tool calling
  return c.json({ message: 'Chat endpoint - Phase 3' })
})
