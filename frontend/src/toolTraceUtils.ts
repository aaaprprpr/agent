import type { GeneratedArtifact, ToolDetail } from './types'

function prettyJson(value: unknown) {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function objectRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

function parseJsonObject(value: unknown): Record<string, unknown> | undefined {
  if (typeof value !== 'string') return objectRecord(value)
  try {
    return objectRecord(JSON.parse(value))
  } catch {
    return undefined
  }
}

function filenameFromPath(value: unknown) {
  if (typeof value !== 'string' || !value.trim()) return undefined
  const normalized = value.replace(/\\/g, '/')
  return normalized.split('/').filter(Boolean).pop()
}

function numberValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function artifactFromRecord(record: Record<string, unknown>): GeneratedArtifact | undefined {
  const downloadUrl = typeof record.download_url === 'string' && record.download_url.trim()
    ? record.download_url.trim()
    : undefined
  if (!downloadUrl) return undefined
  const filename =
    (typeof record.filename === 'string' && record.filename.trim())
      || filenameFromPath(record.relative_output_path)
      || filenameFromPath(record.path)
      || 'generated-file'
  return {
    filename,
    download_url: downloadUrl,
    file_type: typeof record.file_type === 'string' ? record.file_type : undefined,
    suffix: typeof record.suffix === 'string' ? record.suffix : undefined,
    num_bytes: numberValue(record.num_bytes),
    relative_output_path: typeof record.relative_output_path === 'string' ? record.relative_output_path : undefined,
  }
}

function artifactsFromSkillPayload(payload?: Record<string, unknown>) {
  if (!payload) return []
  const result: GeneratedArtifact[] = []
  const output = objectRecord(payload.output)
  if (output) {
    const outputArtifact = artifactFromRecord(output)
    if (outputArtifact) result.push(outputArtifact)
  }
  const artifacts = Array.isArray(payload.artifacts) ? payload.artifacts : []
  artifacts.forEach((item) => {
    const artifact = objectRecord(item)
    if (!artifact) return
    const normalized = artifactFromRecord(artifact)
    if (normalized) result.push(normalized)
  })
  return mergeArtifacts([], result)
}

export function mergeArtifacts(
  existing: GeneratedArtifact[] | undefined,
  incoming: GeneratedArtifact[] | undefined,
) {
  const result: GeneratedArtifact[] = []
  const seen = new Set<string>()
  for (const artifact of [...(existing ?? []), ...(incoming ?? [])]) {
    const key = artifact.download_url || artifact.relative_output_path || artifact.filename
    if (!key || seen.has(key)) continue
    seen.add(key)
    result.push(artifact)
  }
  return result
}

export function artifactsFromToolMessages(messages?: unknown[]) {
  if (!Array.isArray(messages)) return []
  return mergeArtifacts([], messages.flatMap((message) => {
    const record = objectRecord(message)
    return artifactsFromSkillPayload(parseJsonObject(record?.content))
  }))
}

export function artifactsFromToolSteps(steps?: Record<string, unknown>[]) {
  if (!Array.isArray(steps)) return []
  return mergeArtifacts([], steps.flatMap((step) => {
    const output = objectRecord(step.output) ?? parseJsonObject(step.output_json)
    return artifactsFromSkillPayload({ output, artifacts: output ? [output] : [] })
  }))
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

function agentStepFromStep(step: Record<string, unknown>) {
  const input = step.input
  if (!input || typeof input !== 'object') return undefined
  const record = input as Record<string, unknown>
  const direct = record.agent_step
  if (direct && typeof direct === 'object') return direct as Record<string, unknown>
  const beforeTool = record.agent_step_before_tool
  if (beforeTool && typeof beforeTool === 'object') return beforeTool as Record<string, unknown>
  return undefined
}

function stringList(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0) : []
}

function agentStepBody(step: Record<string, unknown>) {
  const lines: string[] = []
  const plan = typeof step.plan === 'string' ? step.plan.trim() : ''
  const observation = typeof step.observation === 'string' ? step.observation.trim() : ''
  const facts = stringList(step.known_facts)
  const missing = stringList(step.missing_info)
  const next = typeof step.next_step === 'string' ? step.next_step.trim() : ''
  if (plan) lines.push(`处理：${plan}`)
  if (observation) lines.push(`结果：${observation}`)
  if (facts.length > 0) lines.push(`依据：${facts.join('；')}`)
  if (missing.length > 0) lines.push(`还需要：${missing.join('；')}`)
  if (next) lines.push(`下一步：${next}`)
  return lines.join('\n')
}

export function toolDetailsFromAgentStep(step?: Record<string, unknown>): ToolDetail[] {
  if (!step || typeof step !== 'object') return []
  const body = agentStepBody(step)
  if (!body) return []
  const phase = typeof step.phase === 'string' ? step.phase : ''
  const label = phase === 'final' || phase === 'observation' ? '观察' : '思考'
  return [{ label, body, kind: 'agent' as const }]
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
  const seenAgentSteps = new Set<string>()
  steps.forEach((step, index) => {
    const agentStep = agentStepFromStep(step)
    for (const detail of toolDetailsFromAgentStep(agentStep)) {
      const key = `${detail.label}:${detail.body}`
      if (!seenAgentSteps.has(key)) {
        seenAgentSteps.add(key)
        details.push(detail)
      }
    }
    const progress = progressTextFromStep(step)
    if (progress && !seenProgress.has(progress)) {
      seenProgress.add(progress)
      details.push(...toolDetailsFromProgress(progress))
    }
    if (step.tool_name === 'agent_observation') return
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
