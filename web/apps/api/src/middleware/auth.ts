import { createMiddleware } from 'hono/factory'
import { createClient } from '@supabase/supabase-js'
import type { Env } from '../index'

export type AuthContext = {
  userId: string
  accessToken: string
}

export const authMiddleware = createMiddleware<{
  Bindings: Env
  Variables: { auth: AuthContext }
}>(async (c, next) => {
  const authHeader = c.req.header('Authorization')
  if (!authHeader?.startsWith('Bearer ')) {
    return c.json({ error: 'Unauthorized' }, 401)
  }

  const token = authHeader.slice(7)
  const supabase = createClient(c.env.SUPABASE_URL, c.env.SUPABASE_ANON_KEY)

  const { data: { user }, error } = await supabase.auth.getUser(token)
  if (error || !user) {
    return c.json({ error: 'Invalid token' }, 401)
  }

  c.set('auth', { userId: user.id, accessToken: token })
  await next()
})
