import { useQuery } from '@tanstack/react-query'
import { checkWhitelist } from '@/lib/kline'

/** Shared whitelist-gate query used by routes that restrict data access to whitelisted users. */
export function useWhitelistGate(userId: string | undefined) {
  return useQuery({
    queryKey: ['whitelist', userId],
    queryFn: () => checkWhitelist(userId || ''),
    enabled: !!userId,
  })
}
