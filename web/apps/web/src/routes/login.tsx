import { useState } from 'react'
import { useNavigate } from 'react-router'
import { supabase } from '@/lib/supabase'

export function LoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isRegister, setIsRegister] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      if (isRegister) {
        const { error } = await supabase.auth.signUp({ email, password })
        if (error) throw error
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password })
        if (error) throw error
      }
      navigate('/', { replace: true })
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '操作失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-blue-50/30 to-purple-50/20">
      <div className="w-full max-w-sm rounded-2xl border border-border bg-white p-8 shadow-xl shadow-primary/5">
        <div className="mb-8 text-center">
          <h1 className="bg-gradient-to-r from-primary to-purple-500 bg-clip-text text-3xl font-bold text-transparent">
            Wyckoff
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">智能投研助手</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1.5 block text-sm font-medium text-foreground">邮箱</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-xl border border-border bg-muted/30 px-4 py-2.5 text-sm outline-none transition-all focus:border-primary focus:ring-2 focus:ring-primary/20"
              placeholder="your@email.com"
              required
            />
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-foreground">密码</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-xl border border-border bg-muted/30 px-4 py-2.5 text-sm outline-none transition-all focus:border-primary focus:ring-2 focus:ring-primary/20"
              placeholder="••••••••"
              required
              minLength={6}
            />
          </div>

          {error && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-xl bg-gradient-to-r from-primary to-purple-500 px-4 py-2.5 text-sm font-medium text-white shadow-lg shadow-primary/25 transition-all hover:shadow-xl hover:shadow-primary/30 disabled:opacity-50"
          >
            {loading ? '处理中...' : isRegister ? '注册' : '登录'}
          </button>
        </form>

        <p className="mt-5 text-center text-sm text-muted-foreground">
          {isRegister ? '已有账号？' : '没有账号？'}
          <button
            onClick={() => setIsRegister(!isRegister)}
            className="ml-1 font-medium text-primary hover:underline"
          >
            {isRegister ? '登录' : '注册'}
          </button>
        </p>
      </div>
    </div>
  )
}
