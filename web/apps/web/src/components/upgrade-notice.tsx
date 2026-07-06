import { AlertTriangle } from 'lucide-react'
import { TICKFLOW_PURCHASE } from '@wyckoff/shared'
import { usePreferences } from '@/lib/preferences'

export function UpgradeNotice({ message }: { message: string }) {
  const { t } = usePreferences()
  const showUpgrade = message.includes(TICKFLOW_PURCHASE)
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100">
      <span className="inline-flex items-center gap-2"><AlertTriangle size={16} />{message.replace(TICKFLOW_PURCHASE, '')}</span>
      {showUpgrade && (
        <a href={TICKFLOW_PURCHASE} target="_blank" rel="noopener noreferrer" className="rounded-lg bg-amber-700 px-3 py-1.5 text-white hover:bg-amber-800">
          {t('common.tickflowLink')}
        </a>
      )}
    </div>
  )
}
