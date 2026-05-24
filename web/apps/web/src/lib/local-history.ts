export type AnalysisHistoryKind = 'single-analysis' | 'stock-battle' | 'portfolio-diagnosis'

export interface AnalysisHistoryRecord<T = unknown> {
  id: string
  kind: AnalysisHistoryKind
  userKey: string
  title: string
  subtitle: string
  symbols: string[]
  payload: T
  createdAt: string
  version: 1
}

export interface SaveHistoryInput<T> {
  kind: AnalysisHistoryKind
  userId?: string | null
  title: string
  subtitle?: string
  symbols?: string[]
  payload: T
}

const DB_NAME = 'wyckoff-local-history'
const STORE_NAME = 'analysis-history'
const DB_VERSION = 1
const HISTORY_LIMIT = 30

export async function saveAnalysisHistory<T>(input: SaveHistoryInput<T>): Promise<AnalysisHistoryRecord<T>> {
  const record = buildHistoryRecord(input)
  const db = await openHistoryDb()
  await putRecord(db, record)
  await pruneHistory(db, record.kind, record.userKey)
  db.close()
  return record
}

export async function listAnalysisHistory<T>(kind: AnalysisHistoryKind, userId?: string | null): Promise<AnalysisHistoryRecord<T>[]> {
  const db = await openHistoryDb()
  const rows = await getAllRecords<T>(db)
  db.close()
  const userKey = userHistoryKey(userId)
  return rows
    .filter((row) => row.kind === kind && row.userKey === userKey)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    .slice(0, HISTORY_LIMIT)
}

export async function listAllAnalysisHistory<T>(userId?: string | null): Promise<AnalysisHistoryRecord<T>[]> {
  const db = await openHistoryDb()
  const rows = await getAllRecords<T>(db)
  db.close()
  const userKey = userHistoryKey(userId)
  return rows
    .filter((row) => row.userKey === userKey)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    .slice(0, HISTORY_LIMIT * 3)
}

export async function deleteAnalysisHistory(id: string): Promise<void> {
  const db = await openHistoryDb()
  await requestDone(db.transaction(STORE_NAME, 'readwrite').objectStore(STORE_NAME).delete(id))
  db.close()
}

export async function clearAnalysisHistory(kind: AnalysisHistoryKind, userId?: string | null): Promise<void> {
  const db = await openHistoryDb()
  const rows = await getAllRecords(db)
  const userKey = userHistoryKey(userId)
  await Promise.all(rows.filter((row) => row.kind === kind && row.userKey === userKey).map((row) => deleteRecord(db, row.id)))
  db.close()
}

export async function clearAllAnalysisHistory(userId?: string | null): Promise<void> {
  const db = await openHistoryDb()
  const rows = await getAllRecords(db)
  const userKey = userHistoryKey(userId)
  await Promise.all(rows.filter((row) => row.userKey === userKey).map((row) => deleteRecord(db, row.id)))
  db.close()
}

export function userHistoryKey(userId?: string | null): string {
  const input = userId?.trim() || 'anonymous'
  let hash = 2166136261
  for (let i = 0; i < input.length; i++) hash = Math.imul(hash ^ input.charCodeAt(i), 16777619)
  return `u_${(hash >>> 0).toString(36)}`
}

function buildHistoryRecord<T>(input: SaveHistoryInput<T>): AnalysisHistoryRecord<T> {
  const createdAt = new Date().toISOString()
  return {
    id: `${input.kind}:${Date.now()}:${randomToken()}`,
    kind: input.kind,
    userKey: userHistoryKey(input.userId),
    title: input.title,
    subtitle: input.subtitle || '',
    symbols: input.symbols || [],
    payload: input.payload,
    createdAt,
    version: 1,
  }
}

function openHistoryDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => ensureStore(request.result)
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function ensureStore(db: IDBDatabase): void {
  if (db.objectStoreNames.contains(STORE_NAME)) return
  const store = db.createObjectStore(STORE_NAME, { keyPath: 'id' })
  store.createIndex('kind_user', ['kind', 'userKey'], { unique: false })
  store.createIndex('created_at', 'createdAt', { unique: false })
}

function putRecord(db: IDBDatabase, record: AnalysisHistoryRecord): Promise<void> {
  const tx = db.transaction(STORE_NAME, 'readwrite')
  tx.objectStore(STORE_NAME).put(record)
  return transactionDone(tx)
}

function getAllRecords<T>(db: IDBDatabase): Promise<AnalysisHistoryRecord<T>[]> {
  return requestDone(db.transaction(STORE_NAME, 'readonly').objectStore(STORE_NAME).getAll())
}

function deleteRecord(db: IDBDatabase, id: string): Promise<void> {
  const tx = db.transaction(STORE_NAME, 'readwrite')
  tx.objectStore(STORE_NAME).delete(id)
  return transactionDone(tx)
}

async function pruneHistory(db: IDBDatabase, kind: AnalysisHistoryKind, userKey: string): Promise<void> {
  const rows = (await getAllRecords(db))
    .filter((row) => row.kind === kind && row.userKey === userKey)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  await Promise.all(rows.slice(HISTORY_LIMIT).map((row) => deleteRecord(db, row.id)))
}

function requestDone<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function transactionDone(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
    tx.onabort = () => reject(tx.error)
  })
}

function randomToken(): string {
  return crypto.randomUUID?.() || Math.random().toString(36).slice(2)
}
