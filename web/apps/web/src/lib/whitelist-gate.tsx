import type { ReactNode } from 'react'
import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { checkWhitelist } from '@/lib/kline'

/** Shared whitelist-gate query used by routes that restrict data access to whitelisted users. */
export function useWhitelistGate(userId: string | undefined) {
  return useQuery({
    queryKey: ['whitelist', userId],
    queryFn: () => checkWhitelist(userId || ''),
    enabled: !!userId,
  })
}

/**
 * For routes that gate their entire page behind whitelist status: returns the loading/locked
 * view to render, or `null` once the caller is whitelisted and should render its real content.
 */
export function whitelistGateView(whitelist: UseQueryResult<boolean>, loadingView: ReactNode, lockedView: ReactNode): ReactNode | null {
  if (whitelist.isLoading) return loadingView
  if (whitelist.data !== true) return lockedView
  return null
}
