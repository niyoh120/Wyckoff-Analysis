import { describe, expect, it } from 'vitest'
import {
  buildSettingsCapabilityRows,
  summarizeSettingsCapabilities,
  type SettingsCapabilityId,
  type SettingsCapabilityRow,
} from '../settings-capabilities'

function findRow(rows: SettingsCapabilityRow[], id: SettingsCapabilityId): SettingsCapabilityRow {
  const row = rows.find((item) => item.id === id)
  expect(row).toBeDefined()
  return row!
}

describe('settings capabilities', () => {
  it('marks key settings missing when credentials are empty', () => {
    const rows = buildSettingsCapabilityRows({
      tickflow: '',
      modelProviderLabel: 'DeepSeek',
      modelConfig: { api_key: '', model: '' },
    })
    const summary = summarizeSettingsCapabilities(rows)

    expect(findRow(rows, 'market-data').status).toBe('missing_config')
    expect(findRow(rows, 'reading-model').status).toBe('missing_config')
    expect(summary).toMatchObject({
      readyCount: 0,
      missingCount: 2,
      totalCount: 2,
      hasCrossMarketKline: false,
      hasReadingModel: false,
      isFullyConfigured: false,
    })
  })

  it('treats TickFlow as the cross-market primary data source', () => {
    const rows = buildSettingsCapabilityRows({
      tickflow: ' tf-key ',
      modelProviderLabel: 'DeepSeek',
      modelConfig: { api_key: '', model: '' },
    })
    const tickflow = findRow(rows, 'market-data')
    const summary = summarizeSettingsCapabilities(rows)

    expect(tickflow.isReady).toBe(true)
    expect(tickflow.priority).toBe('primary')
    expect(summary.hasCrossMarketKline).toBe(true)
    expect(summary.readyCount).toBe(1)
  })

  it('requires both an API key and model name for the reading model', () => {
    const missingModelRows = buildSettingsCapabilityRows({
      tickflow: '',
      modelProviderLabel: 'DeepSeek',
      modelConfig: { api_key: 'deepseek-key', model: '' },
    })
    const readyRows = buildSettingsCapabilityRows({
      tickflow: '',
      modelProviderLabel: 'DeepSeek',
      modelConfig: { api_key: 'deepseek-key', model: 'deepseek-chat' },
    })

    expect(findRow(missingModelRows, 'reading-model').isReady).toBe(false)
    expect(findRow(readyRows, 'reading-model').isReady).toBe(true)
    expect(findRow(readyRows, 'reading-model').badgeLabels).toEqual(['deepseek-chat'])
  })

  it('summarizes fully configured key settings', () => {
    const rows = buildSettingsCapabilityRows({
      tickflow: 'tf-key',
      modelProviderLabel: 'DeepSeek',
      modelConfig: { api_key: 'deepseek-key', model: 'deepseek-chat' },
    })

    expect(summarizeSettingsCapabilities(rows)).toMatchObject({
      readyCount: 2,
      missingCount: 0,
      totalCount: 2,
      hasCrossMarketKline: true,
      hasReadingModel: true,
      isFullyConfigured: true,
    })
  })
})
