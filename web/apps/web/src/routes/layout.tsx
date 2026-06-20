import { Outlet, Link, useLocation, useNavigate } from 'react-router'
import { useCallback, useEffect, useState } from 'react'
import { MessageSquare, Briefcase, TrendingUp, Settings, LogOut, BarChart3, Moon, FileDown, BookOpen, Home, Github, Sun, Languages, Swords, Map, History, Microscope, PanelLeftClose, PanelLeftOpen, type LucideIcon } from 'lucide-react'
import { supabase } from '@/lib/supabase'
import { useAuthStore } from '@/stores/auth'
import { MarketBar } from '@/components/market-bar'
import { usePreferences, type TranslationKey } from '@/lib/preferences'
import { trackRouteActivity } from '@/lib/activity'

const navItems = [
  { to: '/chat', icon: MessageSquare, labelKey: 'nav.chat' },
  { to: '/analysis', icon: BarChart3, labelKey: 'nav.analysis' },
  { to: '/battle', icon: Swords, labelKey: 'nav.battle' },
  { to: '/portfolio', icon: Briefcase, labelKey: 'nav.portfolio' },
  { to: '/history', icon: History, labelKey: 'nav.history' },
  { to: '/tracking', icon: TrendingUp, labelKey: 'nav.tracking' },
  { to: '/attribution', icon: Microscope, labelKey: 'nav.attribution' },
  { to: '/tail-buy', icon: Moon, labelKey: 'nav.tailBuy' },
  { to: '/export', icon: FileDown, labelKey: 'nav.export' },
  { to: '/guide', icon: BookOpen, labelKey: 'nav.guide' },
  { to: '/guide#capability-boundary', icon: Map, labelKey: 'nav.capabilities' },
  { to: '/settings', icon: Settings, labelKey: 'nav.settings' },
] satisfies { to: string; icon: LucideIcon; labelKey: TranslationKey }[]

const externalLinks = [
  { href: 'https://youngcan-wang.github.io/wyckoff-homepage/', icon: Home, labelKey: 'external.home' },
] satisfies { href: string; icon: LucideIcon; labelKey: TranslationKey }[]

const GITHUB_REPO = 'YoungCan-Wang/WyckoffTradingAgent'
const APP_SIDEBAR_STORAGE_KEY = 'wyckoff:app-sidebar-collapsed-v1'

function GitHubStarBadge({ repo }: { repo: string }) {
  return (
    <a
      href={`https://github.com/${repo}`}
      target="_blank"
      rel="noopener noreferrer"
      className="mb-2 flex w-fit items-center overflow-hidden rounded-md border border-border text-xs transition-colors hover:border-muted-foreground/50"
    >
      <span className="flex items-center gap-1.5 bg-muted/60 px-2.5 py-1.5 font-medium text-foreground">
        <Github size={14} />
        Star
      </span>
      <img
        src={`https://img.shields.io/github/stars/${repo}?style=social&label=`}
        alt="stars"
        className="h-[26px] border-l border-border bg-background px-2"
      />
    </a>
  )
}

function PreferenceControls({ collapsed = false }: { collapsed?: boolean }) {
  const { locale, setLocale, theme, toggleTheme, t } = usePreferences()
  const nextLocale = locale === 'zh-CN' ? 'en-US' : 'zh-CN'
  const ThemeIcon = theme === 'dark' ? Sun : Moon

  if (collapsed) {
    return (
      <div className="mb-3 grid gap-2 px-1">
        <button
          type="button"
          onClick={toggleTheme}
          title={theme === 'dark' ? t('prefs.light') : t('prefs.dark')}
          aria-label={t('prefs.theme')}
          className="flex h-9 w-full items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <ThemeIcon size={15} />
        </button>
        <button
          type="button"
          onClick={() => setLocale(nextLocale)}
          title={locale === 'zh-CN' ? t('prefs.switchToEnglish') : t('prefs.switchToChinese')}
          aria-label={t('prefs.language')}
          className="flex h-9 w-full items-center justify-center rounded-lg border border-border text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          {locale === 'zh-CN' ? 'EN' : '中'}
        </button>
      </div>
    )
  }

  return (
    <div className="mb-3 flex gap-2 px-3">
      <button
        type="button"
        onClick={toggleTheme}
        title={theme === 'dark' ? t('prefs.light') : t('prefs.dark')}
        aria-label={t('prefs.theme')}
        className="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg border border-border text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <ThemeIcon size={14} />
        {theme === 'dark' ? t('prefs.light') : t('prefs.dark')}
      </button>
      <button
        type="button"
        onClick={() => setLocale(nextLocale)}
        title={locale === 'zh-CN' ? t('prefs.switchToEnglish') : t('prefs.switchToChinese')}
        aria-label={t('prefs.language')}
        className="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg border border-border text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <Languages size={14} />
        {locale === 'zh-CN' ? 'EN' : '中文'}
      </button>
    </div>
  )
}

function SidebarFooter({ collapsed, email, onLogout }: { collapsed: boolean; email: string; onLogout: () => void }) {
  const { t } = usePreferences()

  if (collapsed) {
    return (
      <div className="border-t border-border p-2">
        <PreferenceControls collapsed />
        {externalLinks.map(({ href, icon: Icon, labelKey }) => (
          <a
            key={href}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            title={t(labelKey)}
            aria-label={t(labelKey)}
            className="mb-2 flex h-9 w-full items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Icon size={16} />
          </a>
        ))}
        <button
          onClick={onLogout}
          title={t('action.logout')}
          aria-label={t('action.logout')}
          className="flex h-9 w-full items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <LogOut size={16} />
        </button>
      </div>
    )
  }

  return (
    <div className="border-t border-border p-3">
      <PreferenceControls />
      {externalLinks.map(({ href, icon: Icon, labelKey }) => (
        <a
          key={href}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="mb-2 flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <Icon size={14} />
          {t(labelKey)}
        </a>
      ))}
      <div className="px-3">
        <GitHubStarBadge repo={GITHUB_REPO} />
      </div>
      <div className="mb-2 truncate px-3 text-[11px] text-muted-foreground">{email}</div>
      <button
        onClick={onLogout}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <LogOut size={15} />
        {t('action.logout')}
      </button>
    </div>
  )
}

export function AppLayout() {
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const { t } = usePreferences()
  const handleLogout = useLogoutHandler()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => readBooleanStorage(APP_SIDEBAR_STORAGE_KEY, false))
  useRouteActivity(user?.id, location)
  const hideMarketBar = location.pathname === '/chat'
  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((value) => {
      const next = !value
      writeBooleanStorage(APP_SIDEBAR_STORAGE_KEY, next)
      return next
    })
  }, [])

  return (
    <div className="flex h-dvh overflow-hidden">
      <aside className={`flex h-full shrink-0 flex-col overflow-hidden border-r border-border bg-sidebar transition-[width] duration-200 ${sidebarCollapsed ? 'w-16' : 'w-56'}`}>
        {sidebarCollapsed ? (
          <div className="flex shrink-0 flex-col items-center gap-2 px-2 py-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-sm font-bold text-primary">W</div>
            <button type="button" onClick={toggleSidebar} title="展开导航" aria-label="展开导航" className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground">
              <PanelLeftOpen size={16} />
            </button>
          </div>
        ) : (
          <div className="flex shrink-0 items-start justify-between gap-3 px-5 py-5">
            <div className="min-w-0">
              <h2 className="bg-gradient-to-r from-primary to-cyan-500 bg-clip-text text-xl font-bold tracking-tight text-transparent">
                Wyckoff
              </h2>
              <p className="mt-0.5 text-[11px] text-muted-foreground">{t('app.subtitle')}</p>
            </div>
            <button type="button" onClick={toggleSidebar} title="收起导航" aria-label="收起导航" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground">
              <PanelLeftClose size={16} />
            </button>
          </div>
        )}

        <nav className={`min-h-0 flex-1 space-y-0.5 overflow-y-auto pb-3 ${sidebarCollapsed ? 'px-2' : 'px-3'}`}>
          {navItems.map(({ to, icon: Icon, labelKey }) => (
            <Link
              key={to}
              to={to}
              title={sidebarCollapsed ? t(labelKey) : undefined}
              aria-label={sidebarCollapsed ? t(labelKey) : undefined}
              className={`flex items-center rounded-lg py-2.5 text-sm transition-all ${sidebarCollapsed ? 'justify-center px-2' : 'gap-3 px-3'} ${
                _navActive(location.pathname, location.hash, to)
                  ? 'bg-primary/10 font-medium text-primary shadow-sm'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
            >
              <Icon size={18} className="shrink-0" />
              {!sidebarCollapsed && t(labelKey)}
            </Link>
          ))}
        </nav>

        <SidebarFooter collapsed={sidebarCollapsed} email={user?.email || 'dev@preview'} onLogout={handleLogout} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {!hideMarketBar && <MarketBar />}
        <main className="min-h-0 flex-1 overflow-auto bg-background">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function readBooleanStorage(key: string, fallback: boolean): boolean {
  if (typeof window === 'undefined') return fallback
  try {
    const value = window.localStorage.getItem(key)
    if (value === 'true') return true
    if (value === 'false') return false
  } catch {
    return fallback
  }
  return fallback
}

function writeBooleanStorage(key: string, value: boolean) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(key, value ? 'true' : 'false')
  } catch {
    // localStorage may be unavailable; the sidebar still works for this session.
  }
}

function _navActive(pathname: string, hash: string, to: string) {
  const [targetPath, targetHash = ''] = to.split('#')
  if (targetHash) {
    return pathname === targetPath && hash === `#${targetHash}`
  }
  return pathname === targetPath && !hash
}

function useLogoutHandler() {
  const navigate = useNavigate()
  return async () => {
    await supabase.auth.signOut()
    navigate('/login', { replace: true })
  }
}

function useRouteActivity(userId: string | undefined, location: ReturnType<typeof useLocation>) {
  const route = `${location.pathname}${location.search}${location.hash}`
  useEffect(() => {
    if (userId) trackRouteActivity(userId, route)
  }, [route, userId])
}
