import { Outlet, Link, useLocation, useNavigate } from 'react-router'
import { useEffect } from 'react'
import { MessageSquare, Briefcase, TrendingUp, Settings, LogOut, BarChart3, Moon, FileDown, BookOpen, Home, Github, Sun, Languages, Swords, Map, History, Microscope, type LucideIcon } from 'lucide-react'
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

function PreferenceControls() {
  const { locale, setLocale, theme, toggleTheme, t } = usePreferences()
  const nextLocale = locale === 'zh-CN' ? 'en-US' : 'zh-CN'
  const ThemeIcon = theme === 'dark' ? Sun : Moon

  return (
    <div className="mb-3 flex gap-2 px-3">
      <button
        type="button"
        onClick={toggleTheme}
        title={theme === 'dark' ? t('prefs.light') : t('prefs.dark')}
        aria-label={t('prefs.theme')}
        className="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-md border border-border text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <ThemeIcon size={14} />
        {theme === 'dark' ? t('prefs.light') : t('prefs.dark')}
      </button>
      <button
        type="button"
        onClick={() => setLocale(nextLocale)}
        title={locale === 'zh-CN' ? t('prefs.switchToEnglish') : t('prefs.switchToChinese')}
        aria-label={t('prefs.language')}
        className="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-md border border-border text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <Languages size={14} />
        {locale === 'zh-CN' ? 'EN' : '中文'}
      </button>
    </div>
  )
}

function SidebarFooter({ email, onLogout }: { email: string; onLogout: () => void }) {
  const { t } = usePreferences()

  return (
    <div className="border-t border-border p-3">
      <PreferenceControls />
      {externalLinks.map(({ href, icon: Icon, labelKey }) => (
        <a
          key={href}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="mb-2 flex items-center gap-2 rounded-md px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
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
        className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
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
  useRouteActivity(user?.id, location)

  return (
    <div className="flex h-dvh overflow-hidden">
      <aside className="flex h-full w-56 shrink-0 flex-col overflow-hidden border-r border-border bg-sidebar">
        <div className="shrink-0 px-5 py-5">
          <h2 className="text-xl font-semibold text-foreground">
            Wyckoff
          </h2>
          <p className="mt-0.5 text-[11px] text-muted-foreground">{t('app.subtitle')}</p>
        </div>

        <nav className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-3 pb-3">
          {navItems.map(({ to, icon: Icon, labelKey }) => (
            <Link
              key={to}
              to={to}
              className={`flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors ${
                _navActive(location.pathname, location.hash, to)
                  ? 'bg-foreground font-medium text-background'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
            >
              <Icon size={18} />
              {t(labelKey)}
            </Link>
          ))}
        </nav>

        <SidebarFooter email={user?.email || 'dev@preview'} onLogout={handleLogout} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <MarketBar />
        <main className="min-h-0 flex-1 overflow-auto bg-background">
          <Outlet />
        </main>
      </div>
    </div>
  )
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
