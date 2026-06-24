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
      <button type="button" onClick={toggleTheme} className="flex h-9 w-9 items-center justify-center rounded-lg border border-border text-muted-foreground hover:bg-muted hover:text-foreground" aria-label={t('prefs.theme')}>
        <ThemeIcon size={16} />
      </button>
      <button type="button" onClick={() => setLocale(locale === 'zh-CN' ? 'en-US' : 'zh-CN')} className="flex h-9 items-center gap-1.5 rounded-lg border border-border px-2.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground" aria-label={t('prefs.language')}>
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
      <h1 className="bg-gradient-to-r from-primary to-cyan-500 bg-clip-text text-3xl font-bold text-transparent">
        Wyckoff
      </h1>
      <p className="mt-1 text-sm text-muted-foreground">{t('app.subtitle')}</p>
    </div>
  )
}

interface LoginFieldsProps {
  email: string
  password: string
  rememberEmail: boolean
  isRegister: boolean
  onEmail: (value: string) => void
  onPassword: (value: string) => void
  onRememberEmail: (value: boolean) => void
}

function LoginFields(props: LoginFieldsProps) {
  return (
    <>
      <LoginEmailField value={props.email} onInput={props.onEmail} />
      <LoginPasswordField value={props.password} isRegister={props.isRegister} onInput={props.onPassword} />
      <RememberEmailCheckbox checked={props.rememberEmail} onChange={props.onRememberEmail} />
    </>
  )
}

function LoginEmailField({ value, onInput }: { value: string; onInput: (value: string) => void }) {
  const { t } = usePreferences()
  return (
    <div>
      <label className="mb-1.5 block text-xs font-semibold text-muted-foreground">{t('login.email')}</label>
      <input
        type="email"
        value={value}
        onChange={(e) => onInput(e.target.value)}
        className="w-full rounded-xl border border-border bg-background/50 px-4 py-2.5 text-sm outline-none transition-all duration-200 focus:bg-background focus:ring-2 focus:ring-primary/20 focus:border-primary placeholder:text-muted-foreground/50"
        placeholder="your@email.com"
        autoComplete="email"
        required
      />
    </div>
  )
}

function LoginPasswordField({ value, isRegister, onInput }: { value: string; isRegister: boolean; onInput: (value: string) => void }) {
  const { t } = usePreferences()
  return (
    <div>
      <label className="mb-1.5 block text-xs font-semibold text-muted-foreground">{t('login.password')}</label>
      <input
        type="password"
        value={value}
        onChange={(e) => onInput(e.target.value)}
        className="w-full rounded-xl border border-border bg-background/50 px-4 py-2.5 text-sm outline-none transition-all duration-200 focus:bg-background focus:ring-2 focus:ring-primary/20 focus:border-primary placeholder:text-muted-foreground/50"
        placeholder="••••••••"
        autoComplete={isRegister ? 'new-password' : 'current-password'}
        required
        minLength={6}
      />
    </div>
  )
}

function RememberEmailCheckbox({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  const { t } = usePreferences()
  return (
    <label className="flex items-start gap-2.5 rounded-xl border border-border bg-muted/10 hover:bg-muted/20 px-3 py-2.5 text-xs text-muted-foreground transition-colors cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 accent-primary cursor-pointer"
      />
      <span>
        <span className="block font-semibold text-foreground">{t('login.rememberAccount')}</span>
        <span className="block text-[11px] mt-0.5 text-muted-foreground/80">{t('login.passwordManagerHint')}</span>
      </span>
    </label>
  )
}

function LoginSubmit(props: { loading: boolean; isRegister: boolean; error: string }) {
  const { t } = usePreferences()
  return (
    <>
      {props.error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-500/10 dark:text-red-200">{props.error}</p>}
      <button type="submit" disabled={props.loading} className="w-full rounded-xl bg-gradient-to-r from-primary to-cyan-500 px-4 py-2.5 text-sm font-medium text-white shadow-lg shadow-primary/25 transition-all hover:shadow-xl hover:shadow-primary/30 disabled:opacity-50">
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
    <div className="relative flex min-h-screen items-center justify-center bg-background px-4 overflow-hidden">
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808008_1px,transparent_1px),linear-gradient(to_bottom,#80808008_1px,transparent_1px)] bg-[size:24px_24px] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_50%,#000_70%,transparent_100%)] pointer-events-none" />
      <LoginToolbar />
      <div className="w-full max-w-sm rounded-3xl border border-border/80 bg-card/85 backdrop-blur-md p-8 shadow-2xl shadow-primary/5 hover:border-primary/20 transition-all duration-300 relative z-10 animate-fade-in-up">
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
