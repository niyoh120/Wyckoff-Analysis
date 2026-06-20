import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { Languages, Moon, Sun } from 'lucide-react'
import { supabase } from '@/lib/supabase'
import { useAuthStore } from '@/stores/auth'
import { usePreferences } from '@/lib/preferences'

const REMEMBERED_EMAIL_KEY = 'wyckoff.login.email'

function readRememberedEmail() {
  try {
    return window.localStorage.getItem(REMEMBERED_EMAIL_KEY) ?? ''
  } catch {
    return ''
  }
}

function saveRememberedEmail(remember: boolean, email: string) {
  try {
    if (remember) {
      window.localStorage.setItem(REMEMBERED_EMAIL_KEY, email.trim())
      return
    }
    window.localStorage.removeItem(REMEMBERED_EMAIL_KEY)
  } catch {
    // localStorage can be disabled by privacy settings; login should still work.
  }
}

function useSessionRedirect() {
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)
  const [checkingSession, setCheckingSession] = useState(true)

  useEffect(() => {
    let active = true
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!active) return
      if (session) {
        setAuth(session.user, session)
        navigate('/', { replace: true })
        return
      }
      setCheckingSession(false)
    }).catch(() => active && setCheckingSession(false))

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!active || !session) return
      setAuth(session.user, session)
      navigate('/', { replace: true })
    })
    return () => {
      active = false
      subscription.unsubscribe()
    }
  }, [navigate, setAuth])

  return { checkingSession, navigate, setAuth }
}

function LoginToolbar() {
  const { locale, setLocale, theme, toggleTheme, t } = usePreferences()
  const ThemeIcon = theme === 'dark' ? Sun : Moon

  return (
    <div className="absolute right-4 top-4 flex gap-2">
      <button type="button" onClick={toggleTheme} className="flex h-9 w-9 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-muted hover:text-foreground" aria-label={t('prefs.theme')}>
        <ThemeIcon size={16} />
      </button>
      <button type="button" onClick={() => setLocale(locale === 'zh-CN' ? 'en-US' : 'zh-CN')} className="flex h-9 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground" aria-label={t('prefs.language')}>
        <Languages size={15} />
        {locale === 'zh-CN' ? 'EN' : '中文'}
      </button>
    </div>
  )
}

function LoginPageHeader() {
  const { t } = usePreferences()
  return (
    <div className="mb-8 text-center">
      <h1 className="text-3xl font-semibold text-foreground">
        Wyckoff
      </h1>
      <p className="mt-1 text-sm text-muted-foreground">{t('app.subtitle')}</p>
    </div>
  )
}

function LoginFields(props: {
  email: string
  password: string
  rememberEmail: boolean
  isRegister: boolean
  onEmail: (value: string) => void
  onPassword: (value: string) => void
  onRememberEmail: (value: boolean) => void
}) {
  const { t } = usePreferences()
  return (
    <>
      <div>
        <label className="mb-1.5 block text-sm font-medium text-foreground">{t('login.email')}</label>
        <input type="email" value={props.email} onChange={(e) => props.onEmail(e.target.value)} className="w-full rounded-md border border-border bg-background px-4 py-2.5 text-sm outline-none transition-colors hover:border-muted-foreground/40" placeholder="your@email.com" autoComplete="email" required />
      </div>
      <div>
        <label className="mb-1.5 block text-sm font-medium text-foreground">{t('login.password')}</label>
        <input type="password" value={props.password} onChange={(e) => props.onPassword(e.target.value)} className="w-full rounded-md border border-border bg-background px-4 py-2.5 text-sm outline-none transition-colors hover:border-muted-foreground/40" placeholder="••••••••" autoComplete={props.isRegister ? 'new-password' : 'current-password'} required minLength={6} />
      </div>
      <label className="flex items-start gap-2.5 rounded-md border border-border bg-muted/40 px-3 py-2.5 text-sm text-muted-foreground">
        <input type="checkbox" checked={props.rememberEmail} onChange={(e) => props.onRememberEmail(e.target.checked)} className="mt-0.5 h-4 w-4 accent-primary" />
        <span>
          <span className="block font-medium text-foreground">{t('login.rememberAccount')}</span>
          <span className="block text-xs">{t('login.passwordManagerHint')}</span>
        </span>
      </label>
    </>
  )
}

function LoginSubmit(props: { loading: boolean; isRegister: boolean; error: string }) {
  const { t } = usePreferences()
  return (
    <>
      {props.error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-500/10 dark:text-red-200">{props.error}</p>}
      <button type="submit" disabled={props.loading} className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground">
        {props.loading ? t('login.processing') : props.isRegister ? t('login.register') : t('login.submit')}
      </button>
    </>
  )
}

function RegisterSwitch(props: { isRegister: boolean; onToggle: () => void }) {
  const { t } = usePreferences()
  return (
    <p className="mt-5 text-center text-sm text-muted-foreground">
      {props.isRegister ? t('login.hasAccount') : t('login.noAccount')}
      <button type="button" onClick={props.onToggle} className="ml-1 font-medium text-primary hover:underline">
        {props.isRegister ? t('login.submit') : t('login.register')}
      </button>
    </p>
  )
}

export function LoginPage() {
  const { checkingSession, navigate, setAuth } = useSessionRedirect()
  const { t } = usePreferences()
  const [email, setEmail] = useState(readRememberedEmail)
  const [password, setPassword] = useState('')
  const [rememberEmail, setRememberEmail] = useState(() => Boolean(readRememberedEmail()))
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
        const { data, error } = await supabase.auth.signInWithPassword({ email, password })
        if (error) throw error
        if (data.session) setAuth(data.user, data.session)
      }
      saveRememberedEmail(rememberEmail, email)
      navigate('/', { replace: true })
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t('login.operationFailed'))
    } finally {
      setLoading(false)
    }
  }

  if (checkingSession) return <LoadingSession />
  return (
    <div className="relative flex min-h-screen items-center justify-center bg-background px-4">
      <LoginToolbar />
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-8 shadow-[0_2px_2px_rgba(0,0,0,0.04)]">
        <LoginPageHeader />
        <form onSubmit={handleSubmit} className="space-y-4">
          <LoginFields email={email} password={password} rememberEmail={rememberEmail} isRegister={isRegister} onEmail={setEmail} onPassword={setPassword} onRememberEmail={setRememberEmail} />
          <LoginSubmit loading={loading} isRegister={isRegister} error={error} />
        </form>
        <RegisterSwitch isRegister={isRegister} onToggle={() => setIsRegister(!isRegister)} />
      </div>
    </div>
  )
}

function LoadingSession() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
    </div>
  )
}
