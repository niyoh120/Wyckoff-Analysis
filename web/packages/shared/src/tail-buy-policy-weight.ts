import { formatPolicyWeightMetaText } from './policy-weight-meta'

export interface TailBuyPolicyWeightInput {
  features_json?: unknown
  signal_type?: unknown
}

export interface TailBuyPolicyWeightFormatOptions {
  prefix?: string
  emptyText?: string
}

export function formatTailBuyPolicyWeightText(
  row: TailBuyPolicyWeightInput,
  options: TailBuyPolicyWeightFormatOptions = {},
): string {
  const features = jsonMapOrNull(row.features_json)
  const multiplier = features ? numberOrNull(features.policy_weight_multiplier) : null
  if (multiplier === null) return options.emptyText ?? ''

  const signal = String(features?.policy_weight_signal || row.signal_type || 'unknown')
  const oldScore = features ? numberOrNull(features.policy_weight_old_score) : null
  const newScore = features ? numberOrNull(features.policy_weight_new_score) : null
  const scoreText = oldScore !== null && newScore !== null ? ` ${oldScore.toFixed(1)}→${newScore.toFixed(1)}` : ''
  return `${options.prefix ?? ''}${signal} x${multiplier.toFixed(2)}${scoreText}${formatPolicyWeightMetaText(features)}`
}

export function tailBuyPolicyWeightMultiplier(row: TailBuyPolicyWeightInput): number | undefined {
  const features = jsonMapOrNull(row.features_json)
  const multiplier = features ? numberOrNull(features.policy_weight_multiplier) : null
  return multiplier ?? undefined
}

function jsonMapOrNull(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>
  if (typeof value !== 'string' || value.trim() === '') return null
  try {
    const parsed = JSON.parse(value) as unknown
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null
  } catch {
    return null
  }
}

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}
