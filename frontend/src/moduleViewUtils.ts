export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function asRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

export function parseJsonObject(text: string) {
  try {
    const value = JSON.parse(text)
    return isRecord(value) ? value : undefined
  } catch {
    return undefined
  }
}

export function prettyValue(value: unknown) {
  if (value === undefined || value === null || value === '') return '无'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function compactValue(value: unknown, limit = 120) {
  const text = prettyValue(value).replace(/\s+/g, ' ').trim()
  if (!text || text === '无') return '无'
  return text.length > limit ? `${text.slice(0, limit)}...` : text
}

export function getRecordString(value: Record<string, unknown> | undefined, key: string, fallback = '无') {
  const item = value?.[key]
  if (item === undefined || item === null || item === '') return fallback
  if (typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean') return String(item)
  return fallback
}

export function getRecordNumber(value: Record<string, unknown> | undefined, key: string, fallback = 0) {
  const item = value?.[key]
  if (typeof item === 'number' && Number.isFinite(item)) return item
  if (typeof item === 'string') {
    const parsed = Number(item)
    if (Number.isFinite(parsed)) return parsed
  }
  return fallback
}

export function getRecordList(value: Record<string, unknown> | undefined, key: string, limit = 6) {
  const item = value?.[key]
  if (!Array.isArray(item)) return []
  return item.slice(0, limit).map((entry) => String(entry))
}

export function boolText(value: unknown) {
  if (value === true) return 'true'
  if (value === false) return 'false'
  return 'unknown'
}

export function toolNameFromLabel(label: string) {
  return label
    .replace(/^\d+\.\s*/, '')
    .replace(/^调用\s*/, '')
    .replace(/^结果\s*/, '')
    .trim()
    .split(/\s+/)[0] || label
}

export function statusClass(status: string) {
  const normalized = status.toLowerCase()
  if (normalized.includes('error') || normalized.includes('fail')) return 'error'
  if (normalized.includes('success') || normalized.includes('done')) return 'success'
  return 'pending'
}

export function artifactHref(downloadUrl: unknown, apiBase: string) {
  if (typeof downloadUrl !== 'string' || !downloadUrl) return ''
  return downloadUrl.startsWith('http') ? downloadUrl : `${apiBase}${downloadUrl}`
}
