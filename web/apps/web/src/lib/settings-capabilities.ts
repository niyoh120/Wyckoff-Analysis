import type { TranslationKey } from './preferences'

export type SettingsCapabilityId = 'market-data' | 'reading-model'
export type SettingsCapabilityStatus = 'ready' | 'missing_config'
export type SettingsCapabilityPriority = 'primary'

export interface SettingsCapabilityInput {
  tickflow?: string | null
  modelProviderLabel: string
  modelConfig?: {
    api_key?: string | null
    model?: string | null
  }
}

export interface SettingsCapabilityDefinition {
  id: SettingsCapabilityId
  name: string
  priority: SettingsCapabilityPriority
  priorityLabelKey: TranslationKey
  badgeLabelKeys: readonly TranslationKey[]
  badgeLabels?: readonly string[]
  capabilityLabelKeys: readonly TranslationKey[]
  noteKey: TranslationKey
}

export interface SettingsCapabilityRow extends SettingsCapabilityDefinition {
  status: SettingsCapabilityStatus
  statusLabelKey: TranslationKey
  isReady: boolean
}

export interface SettingsCapabilitySummary {
  readyCount: number
  missingCount: number
  totalCount: number
  hasCrossMarketKline: boolean
  hasReadingModel: boolean
  isFullyConfigured: boolean
}

const MARKET_DATA_CAPABILITY = {
  id: 'market-data',
  name: 'TickFlow',
  priority: 'primary',
  priorityLabelKey: 'settings.capabilityCategoryData',
  badgeLabelKeys: ['settings.marketCn', 'settings.marketUs', 'settings.marketHk'],
  capabilityLabelKeys: [
    'settings.capabilityDailyKline',
    'settings.capabilityFundamentals',
    'settings.capabilityExport',
    'settings.capabilityCrossMarket',
  ],
  noteKey: 'settings.tickflowCapabilityNote',
} satisfies SettingsCapabilityDefinition

export function buildSettingsCapabilityRows(input: SettingsCapabilityInput): SettingsCapabilityRow[] {
  return [
    buildRow(MARKET_DATA_CAPABILITY, hasCredential(input.tickflow)),
    buildRow({
      id: 'reading-model',
      name: input.modelProviderLabel,
      priority: 'primary',
      priorityLabelKey: 'settings.capabilityCategoryModel',
      badgeLabelKeys: [],
      badgeLabels: input.modelConfig?.model?.trim() ? [input.modelConfig.model.trim()] : [],
      capabilityLabelKeys: [
        'settings.capabilityReadingRoom',
        'settings.capabilityAiReport',
        'settings.capabilityStrategyReasoning',
      ],
      noteKey: 'settings.modelCapabilityNote',
    }, isModelConfigured(input.modelConfig)),
  ]
}

export function summarizeSettingsCapabilities(rows: readonly SettingsCapabilityRow[]): SettingsCapabilitySummary {
  const readyCount = rows.filter((row) => row.isReady).length
  const totalCount = rows.length
  return {
    readyCount,
    missingCount: totalCount - readyCount,
    totalCount,
    hasCrossMarketKline: rows.some((row) => row.id === 'market-data' && row.isReady),
    hasReadingModel: rows.some((row) => row.id === 'reading-model' && row.isReady),
    isFullyConfigured: readyCount === totalCount,
  }
}

function buildRow(definition: SettingsCapabilityDefinition, isReady: boolean): SettingsCapabilityRow {
  return {
    ...definition,
    status: isReady ? 'ready' : 'missing_config',
    statusLabelKey: isReady ? 'settings.capabilityReady' : 'settings.capabilityMissingConfig',
    isReady,
  }
}

function isModelConfigured(modelConfig: SettingsCapabilityInput['modelConfig']): boolean {
  return hasCredential(modelConfig?.api_key) && hasCredential(modelConfig?.model)
}

function hasCredential(value: string | null | undefined): boolean {
  return typeof value === 'string' && value.trim().length > 0
}
