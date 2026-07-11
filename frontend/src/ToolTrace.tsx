import type { ChatMessage, ToolDetail } from './types'

function prettyJson(value: unknown) {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function toolNameFromRecord(value: unknown, fallback: string) {
  if (!value || typeof value !== 'object') return fallback
  const record = value as Record<string, unknown>
  const name = record.name ?? record.tool_name
  return typeof name === 'string' && name.trim() ? name : fallback
}

function progressTextFromStep(step: Record<string, unknown>) {
  const input = step.input
  if (!input || typeof input !== 'object') return ''
  const value = (input as Record<string, unknown>).assistant_content_before_tool
  return typeof value === 'string' ? value.trim() : ''
}

function compactToolStepInput(value: unknown) {
  if (!value || typeof value !== 'object') return value
  const input = value as Record<string, unknown>
  if (input.skill_input !== undefined) return input.skill_input
  const toolCall = input.tool_call
  if (toolCall && typeof toolCall === 'object') {
    const args = (toolCall as Record<string, unknown>).args
    if (args !== undefined) return args
  }
  return value
}

function compactToolStepOutput(value: unknown) {
  if (!value || typeof value !== 'object') return value
  const output = value as Record<string, unknown>
  return output.skill_output !== undefined ? output.skill_output : value
}

export function toolDetailsFromProgress(content?: string) {
  const body = content?.trim()
  if (!body) return []
  return [{ label: '工具前说明', body, status: 'info', kind: 'note' as const }]
}

export function toolDetailsFromCalls(calls?: unknown[]) {
  if (!Array.isArray(calls) || calls.length === 0) return []
  return calls.map((call, index) => ({
    label: `调用 ${toolNameFromRecord(call, `tool_${index + 1}`)}`,
    body: prettyJson(call),
    status: 'pending',
    kind: 'tool' as const,
  }))
}

export function toolDetailsFromSteps(steps?: Record<string, unknown>[]) {
  if (!Array.isArray(steps) || steps.length === 0) return []
  const details: ToolDetail[] = []
  const seenProgress = new Set<string>()
  steps.forEach((step, index) => {
    const progress = progressTextFromStep(step)
    if (progress && !seenProgress.has(progress)) {
      seenProgress.add(progress)
      details.push(...toolDetailsFromProgress(progress))
    }
    details.push({
      label: `${index + 1}. ${toolNameFromRecord(step, 'tool')}`,
      body: prettyJson({
        input: compactToolStepInput(step.input ?? step.input_json),
        output: compactToolStepOutput(step.output ?? step.output_json),
        error: step.error ?? step.error_json,
        latency_ms: step.latency_ms,
      }),
      status: typeof step.status === 'string' ? step.status : undefined,
      kind: 'tool',
    })
  })
  return details
}

export function toolDetailsFromMessages(messages?: unknown[]) {
  if (!Array.isArray(messages) || messages.length === 0) return []
  return messages.map((message, index) => ({
    label: `结果 ${toolNameFromRecord(message, `tool_${index + 1}`)}`,
    body: prettyJson(message),
    status:
      message && typeof message === 'object' && typeof (message as Record<string, unknown>).status === 'string'
        ? String((message as Record<string, unknown>).status)
        : undefined,
    kind: 'tool' as const,
  }))
}

export function LoadingBubble() {
  return (
    <span className="loading-bubble" aria-label="等待回复">
      <span className="loading-dots" aria-hidden="true"><span /><span /><span /></span>
    </span>
  )
}

function ChevronDownIcon() {
  return <svg className="tool-trace-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M4.25 6.25L8 10l3.75-3.75" /></svg>
}

export function ToolTrace({ message, onToggle }: { message: ChatMessage; onToggle: (messageId: number | string) => void }) {
  const details = message.toolDetails ?? []
  if (details.length === 0) return null
  const open = Boolean(message.toolPanelOpen)
  const active = message.status === 'pending'
  const toolCount = details.filter((detail) => detail.kind !== 'note').length || details.length
  return (
    <div className={`tool-trace ${open ? 'open' : ''}`}>
      <button className="tool-trace-toggle" type="button" onClick={() => onToggle(message.id)}>
        <ChevronDownIcon />
        <span>{active ? '处理中' : '工具调用'}</span>
        <small>{toolCount} 项</small>
      </button>
      {open && <div className="tool-trace-panel">
        {details.map((detail, index) => <section className="tool-trace-item" key={`${detail.label}-${index}`}>
          <div className="tool-trace-title"><span>{detail.label}</span>{detail.status && <em>{detail.status}</em>}</div>
          <pre>{detail.body}</pre>
        </section>)}
      </div>}
    </div>
  )
}
