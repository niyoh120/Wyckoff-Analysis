import {
  Activity,
  BarChart3,
  BookOpenCheck,
  ClipboardList,
  Gauge,
  LineChart,
  ListChecks,
  WalletCards,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import type { TranslationKey } from '@/lib/preferences'

export interface DeskScenario {
  id: string
  title: string
  eyebrow: string
  description: string
  prompt: string
  Icon: LucideIcon
  toneClass: string
}

export interface DeskShortcut {
  title: string
  description: string
  prompt: string
  Icon: LucideIcon
  metric: string
}

export const SCENARIOS: DeskScenario[] = [
  {
    id: 'premarket',
    title: '盘前',
    eyebrow: '市场先验',
    description: '水温、持仓、候选池先排队。',
    prompt: '做一次盘前读盘：先看市场水温和风险状态，再结合我的持仓、最新候选池和威科夫形态复盘，给出今天只需要盯的 3 件事。',
    Icon: Gauge,
    toneClass: 'border-sky-200 bg-sky-50/75 text-sky-900 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100',
  },
  {
    id: 'intraday',
    title: '盘中',
    eyebrow: '临场判断',
    description: '先判断该进攻、等待还是防守。',
    prompt: '做一次盘中读盘：先读取市场水温，再判断当前更适合进攻、等待还是防守；如果需要我补股票代码，请直接问我。',
    Icon: Activity,
    toneClass: 'border-emerald-200 bg-emerald-50/75 text-emerald-900 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-100',
  },
  {
    id: 'tail',
    title: '尾盘',
    eyebrow: '明日线索',
    description: '把尾盘机会和漏斗候选合并看。',
    prompt: '做一次尾盘机会筛选：读取尾盘记录和漏斗选股，按证据强弱列出明天值得观察的股票，并给出触发条件和失效条件。',
    Icon: Zap,
    toneClass: 'border-amber-200 bg-amber-50/80 text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100',
  },
  {
    id: 'review',
    title: '复盘',
    eyebrow: '信号归因',
    description: '看哪些信号有效，哪些要降权。',
    prompt: '做一次收盘复盘：回看最近威科夫形态复盘、策略归因和尾盘记录，告诉我哪些信号有效、哪些是噪音，明天应该降权或加权什么。',
    Icon: BookOpenCheck,
    toneClass: 'border-rose-200 bg-rose-50/75 text-rose-900 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-100',
  },
]

export const SHORTCUTS: DeskShortcut[] = [
  {
    title: '市场水温',
    description: '大盘、A50、VIX 和风险状态。',
    prompt: '先读取市场水温，告诉我今天的市场先验、风险级别和仓位倾向。',
    Icon: BarChart3,
    metric: '先验',
  },
  {
    title: '持仓风险',
    description: '把我的持仓按处理优先级排序。',
    prompt: '查看我的持仓，并按“需要处理、继续观察、暂不操作”分组，给出每只票的风险点和下一步。',
    Icon: WalletCards,
    metric: '持仓',
  },
  {
    title: '候选漏斗',
    description: '高分候选先给交易条件。',
    prompt: '运行漏斗选股，把结果按分数、形态阶段和证据强弱排序，并告诉我最值得盯的前 5 只。',
    Icon: ListChecks,
    metric: '候选',
  },
  {
    title: '尾盘记录',
    description: '只看尾盘确认和隔日线索。',
    prompt: '读取尾盘记录，筛出有尾盘确认、次日仍值得观察的标的，并说明为什么。',
    Icon: LineChart,
    metric: '尾盘',
  },
  {
    title: '策略归因',
    description: '用近期结果校准信号权重。',
    prompt: '读取策略归因报告，告诉我最近哪些信号贡献最好、哪些信号需要降权，并把结论用于今天读盘。',
    Icon: ClipboardList,
    metric: '归因',
  },
]

export function chatPromptSuggestions(t: (key: TranslationKey) => string): string[] {
  return [
    t('chat.prompt.portfolio'),
    t('chat.prompt.market'),
    t('chat.prompt.recent'),
    t('chat.prompt.search'),
    t('chat.prompt.screen'),
    t('chat.prompt.strategy'),
  ]
}
