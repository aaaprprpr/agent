function pad(value: number, size = 2) {
  return String(value).padStart(size, '0')
}

export function createConversationId() {
  const now = new Date()
  return [
    'conv_web',
    `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`,
    `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`,
    pad(now.getMilliseconds(), 3),
  ].join('_')
}

export function titleFromInput(text: string) {
  const compact = text.replace(/\s+/g, ' ').trim()
  if (!compact) return '新对话'
  return compact.length > 18 ? `${compact.slice(0, 18)}...` : compact
}
