import { supabase as defaultSupabase } from '@/lib/supabase'
import { APP_VERSION } from '@/lib/app-version'

type SupabaseLike = Pick<typeof defaultSupabase, 'from'>

interface ActivityInput {
  userId: string
  route: string
  eventName?: string
  feature?: string
  source?: string
  success?: boolean
  durationMs?: number
  metadata?: Record<string, unknown>
}

interface ActivityDeps {
  supabase?: SupabaseLike
  now?: () => Date
  eventId?: string
  sessionId?: string
  countSession?: boolean
}

interface ActivityResult {
  eventWritten: boolean
  dailyWritten: boolean
  skipped?: 'excluded' | 'missing-user'
}

interface DailyActivityRow {
  event_count?: number | null
  session_count?: number | null
  sources?: string[] | null
  feature_counts?: Record<string, unknown> | null
  first_seen_at?: string | null
}

let lastRouteKey = ''
let lastRouteAt = 0

export function trackRouteActivity(userId: string, route: string): void {
  const key = `${userId}:${route}`
  const now = Date.now()
  if (lastRouteKey === key && now - lastRouteAt < 1500) return
  lastRouteKey = key
  lastRouteAt = now
  void recordActivity({ userId, route, eventName: 'page_view', feature: featureForRoute(route) })
}

export async function recordActivity(input: ActivityInput, deps: ActivityDeps = {}): Promise<ActivityResult> {
  const userId = input.userId.trim()
  if (!userId) return { eventWritten: false, dailyWritten: false, skipped: 'missing-user' }
  const client = deps.supabase ?? defaultSupabase
  if (await isAnalyticsExcluded(client, userId)) {
    return { eventWritten: false, dailyWritten: false, skipped: 'excluded' }
  }

  const now = deps.now?.() ?? new Date()
  const sessionId = deps.sessionId ?? browserSessionId()
  const eventId = deps.eventId ?? randomId()
  const source = input.source?.trim() || 'web'
  const feature = input.feature?.trim() || featureForRoute(input.route)
  const activityDate = localDateKey(now)
  const nowIso = now.toISOString()
  const eventRow = {
    event_id: eventId,
    user_id: userId,
    source,
    session_id: sessionId,
    event_name: input.eventName?.trim() || 'page_view',
    feature,
    route: input.route,
    success: input.success ?? true,
    duration_ms: input.durationMs ?? null,
    app_version: APP_VERSION,
    metadata: input.metadata ?? {},
    client_ts: nowIso,
  }
  const { error: eventError } = await client.from('user_activity_events').insert(eventRow)
  if (eventError) return { eventWritten: false, dailyWritten: false }

  const countSession = deps.countSession ?? markSessionSeen(activityDate, sessionId)
  const dailyWritten = await upsertDailyActivity(client, userId, activityDate, source, feature, nowIso, countSession)
  return { eventWritten: true, dailyWritten }
}

export function featureForRoute(route: string): string {
  const path = route.split('#')[0]?.split('?')[0] || '/'
  if (path === '/' || path === '/chat') return 'chat'
  const segment = path.split('/').find(Boolean)
  return segment ? segment.replaceAll('-', '_') : 'app'
}

async function isAnalyticsExcluded(client: SupabaseLike, userId: string): Promise<boolean> {
  const { data, error } = await client
    .from('analytics_excluded_users')
    .select('user_id')
    .eq('user_id', userId)
    .limit(1)
  if (error) return false
  return Array.isArray(data) && data.length > 0
}

async function upsertDailyActivity(
  client: SupabaseLike,
  userId: string,
  activityDate: string,
  source: string,
  feature: string,
  nowIso: string,
  countSession: boolean,
): Promise<boolean> {
  const existing = await loadDailyActivity(client, userId, activityDate)
  if (existing === undefined) return false
  const featureCounts = normalizedFeatureCounts(existing?.feature_counts)
  featureCounts[feature] = (featureCounts[feature] ?? 0) + 1
  const payload = {
    activity_date: activityDate,
    user_id: userId,
    sources: sortedUnion(existing?.sources, source),
    event_count: numeric(existing?.event_count) + 1,
    session_count: numeric(existing?.session_count) + (countSession || !existing ? 1 : 0),
    first_seen_at: existing?.first_seen_at || nowIso,
    last_seen_at: nowIso,
    feature_counts: featureCounts,
    updated_at: nowIso,
  }
  const { error } = await client.from('user_daily_activity').upsert(payload, { onConflict: 'activity_date,user_id' })
  return !error
}

async function loadDailyActivity(
  client: SupabaseLike,
  userId: string,
  activityDate: string,
): Promise<DailyActivityRow | null | undefined> {
  const { data, error } = await client
    .from('user_daily_activity')
    .select('event_count,session_count,sources,feature_counts,first_seen_at')
    .eq('user_id', userId)
    .eq('activity_date', activityDate)
    .limit(1)
  if (error) return undefined
  return Array.isArray(data) ? (data[0] as DailyActivityRow | undefined) ?? null : null
}

function normalizedFeatureCounts(raw: Record<string, unknown> | null | undefined): Record<string, number> {
  const out: Record<string, number> = {}
  for (const [key, value] of Object.entries(raw ?? {})) {
    if (typeof value === 'number' && Number.isFinite(value)) out[key] = value
  }
  return out
}

function sortedUnion(values: string[] | null | undefined, value: string): string[] {
  return Array.from(new Set([...(values ?? []), value].filter(Boolean))).sort()
}

function numeric(value: number | null | undefined): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function localDateKey(now: Date): string {
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 10)
}

function browserSessionId(): string {
  if (typeof window === 'undefined') return randomId()
  try {
    const key = 'wyckoff.activity.session_id'
    const existing = window.sessionStorage.getItem(key)
    if (existing) return existing
    const created = randomId()
    window.sessionStorage.setItem(key, created)
    return created
  } catch {
    return randomId()
  }
}

function markSessionSeen(activityDate: string, sessionId: string): boolean {
  if (typeof window === 'undefined') return true
  try {
    const key = `wyckoff.activity.seen.${activityDate}.${sessionId}`
    if (window.sessionStorage.getItem(key)) return false
    window.sessionStorage.setItem(key, '1')
    return true
  } catch {
    return true
  }
}

function randomId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}
