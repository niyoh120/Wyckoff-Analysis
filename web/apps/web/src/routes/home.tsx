import { ExternalLink } from 'lucide-react'

const HOMEPAGE_URL = 'https://youngcan-wang.github.io/wyckoff-homepage/'
const GITHUB_URL = 'https://github.com/YoungCan-Wang/Wyckoff-Analysis'

export function HomePage() {
  return (
    <div className="flex h-full flex-col items-center justify-center p-6">
      <div className="mb-8 text-6xl">📊</div>
      <h1 className="mb-2 bg-gradient-to-r from-primary to-purple-500 bg-clip-text text-3xl font-bold text-transparent">
        Wyckoff Analysis
      </h1>
      <p className="mb-8 text-sm text-muted-foreground">智能投研助手 — 量价分析 · 威科夫方法 · AI Agent</p>

      <div className="flex gap-4">
        <a
          href={HOMEPAGE_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
        >
          <ExternalLink size={16} />
          项目主页
        </a>
        <a
          href={GITHUB_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 rounded-lg border border-border px-5 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-muted/50"
        >
          <ExternalLink size={16} />
          GitHub
        </a>
      </div>
    </div>
  )
}
