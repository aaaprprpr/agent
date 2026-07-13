import { useMemo } from 'react'
import { ArrowLeftRight, ArrowRight, CheckCircle, Circle, XCircle } from 'lucide-react'

import type { ChatMessage, ToolDetail } from './types'

type ModuleMode = 'observe' | 'demo'

type B3ModuleViewProps = {
  mode: ModuleMode
  messages: ChatMessage[]
}

type B3ToolItem = {
  name: string
  status: string
  latencyMs?: number
  input?: unknown
  output?: unknown
  error?: unknown
  raw: string
}

type B3Cycle = {
  id: string
  round: number
  messageIndex: number
  notes: ToolDetail[]
  tools: B3ToolItem[]
}

function parseJsonObject(text: string) {
  try {
    const value = JSON.parse(text)
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
  } catch {
    return undefined
  }
}

function toolNameFromLabel(label: string) {
  return label
    .replace(/^\d+\.\s*/, '')
    .replace(/^调用\s*/, '')
    .replace(/^结果\s*/, '')
    .trim()
    .split(/\s+/)[0] || label
}

function pretty(value: unknown) {
  if (value === undefined || value === null || value === '') return '无'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function compact(value: unknown, limit = 120) {
  const text = pretty(value).replace(/\s+/g, ' ').trim()
  if (!text || text === '无') return '无'
  return text.length > limit ? `${text.slice(0, limit)}...` : text
}

function statusClass(status: string) {
  const normalized = status.toLowerCase()
  if (normalized.includes('error') || normalized.includes('fail')) return 'error'
  if (normalized.includes('success') || normalized.includes('done')) return 'success'
  return 'pending'
}

function toolFromDetail(detail: ToolDetail): B3ToolItem {
  const parsed = parseJsonObject(detail.body)
  const input = parsed?.input ?? parsed?.args
  const output = parsed?.output
  const error = parsed?.error
  const latencyMs = typeof parsed?.latency_ms === 'number' ? parsed.latency_ms : undefined
  const name =
    typeof parsed?.tool_name === 'string' ? parsed.tool_name
      : typeof parsed?.name === 'string' ? parsed.name
        : toolNameFromLabel(detail.label)
  return {
    name,
    status: detail.status || (error ? 'error' : output !== undefined ? 'success' : 'pending'),
    latencyMs,
    input,
    output,
    error,
    raw: detail.body,
  }
}

function collectCycles(messages: ChatMessage[]): B3Cycle[] {
  let round = 0
  return messages.flatMap((message, messageIndex) => {
    if (message.role !== 'assistant' || !message.toolDetails?.length) return []
    const tools = message.toolDetails.filter((detail) => detail.kind === 'tool').map(toolFromDetail)
    if (tools.length === 0) return []
    const notes = message.toolDetails.filter((detail) => detail.kind !== 'tool')
    round += 1
    return [{
      id: String(message.id),
      round,
      messageIndex,
      notes,
      tools,
    }]
  })
}

function StatusIcon({ status }: { status: string }) {
  const cls = statusClass(status)
  if (cls === 'success') return <CheckCircle size={14} strokeWidth={1.9} aria-hidden="true" />
  if (cls === 'error') return <XCircle size={14} strokeWidth={1.9} aria-hidden="true" />
  return <Circle size={14} strokeWidth={1.9} aria-hidden="true" />
}

function ObservationPanel({ messages }: { messages: ChatMessage[] }) {
  const cycles = useMemo(() => collectCycles(messages), [messages])
  const toolCount = cycles.reduce((total, cycle) => total + cycle.tools.length, 0)

  return (
    <div className="b3-module">
      <div className="b3-head">
        <div>
          <span>B3</span>
          <h2>说明生成与工具调用模块</h2>
        </div>
        <div className="b3-summary">
          <span>{cycles.length} 个闭环</span>
          <span>{toolCount} 个工具调用</span>
        </div>
      </div>

      <div className="b3-cycles">
        {cycles.length === 0 ? (
          <p className="b3-empty">当前对话没有经过 B3 的 tool 调用闭环。</p>
        ) : (
          cycles.map((cycle) => (
            <section className="b3-cycle" key={cycle.id}>
              <header className="b3-cycle-head">
                <strong>Round {cycle.round}</strong>
                <span>assistant message #{cycle.messageIndex + 1}</span>
              </header>

              <div className="b3-flow">
                <section className="b3-side b3-llm-side">
                  <h3>LLM 侧</h3>
                  <dl>
                    <dt>AIMessage</dt>
                    <dd>含 tool_calls</dd>
                    <dt>tool_calls</dt>
                    <dd>{cycle.tools.length} 项</dd>
                  </dl>
                  {cycle.notes.length > 0 && (
                    <div className="b3-note-list">
                      {cycle.notes.map((note, index) => (
                        <article key={`${cycle.id}-note-${index}`}>
                          <strong>{note.label}</strong>
                          <p>{compact(note.body, 180)}</p>
                        </article>
                      ))}
                    </div>
                  )}
                </section>

                <div className="b3-arrow">
                  <ArrowRight size={18} strokeWidth={1.8} aria-hidden="true" />
                </div>

                <section className="b3-core">
                  <h3>B3 处理</h3>
                  <div className="b3-core-steps">
                    <div><strong>解析</strong><span>读取 AIMessage.tool_calls</span><em>{cycle.tools.length} 项</em></div>
                    <div><strong>标准化</strong><span>提取 tool name / args / call id</span><em>完成</em></div>
                    <div><strong>校验</strong><span>按 schema 检查必填参数</span><em>{cycle.tools.some((tool) => statusClass(tool.status) === 'error') ? '存在失败' : '通过'}</em></div>
                    <div><strong>分发</strong><span>转交 B2 执行 skill 函数</span><em>{cycle.tools.length} 次</em></div>
                    <div><strong>包装</strong><span>把 B2 结果转回 ToolMessage / trace</span><em>返回 B1</em></div>
                  </div>
                </section>

                <div className="b3-arrow back">
                  <ArrowLeftRight size={18} strokeWidth={1.8} aria-hidden="true" />
                </div>

                <section className="b3-side b3-tool-side">
                  <h3>Tool 侧</h3>
                  <div className="b3-tool-list">
                    {cycle.tools.map((tool, index) => (
                      <article className="b3-tool-card" key={`${cycle.id}-tool-${index}`}>
                        <header>
                          <span className={statusClass(tool.status)}>
                            <StatusIcon status={tool.status} />
                          </span>
                          <strong>{tool.name}</strong>
                          <em>{tool.status}</em>
                        </header>
                        <dl>
                          <dt>latency</dt>
                          <dd>{tool.latencyMs !== undefined ? `${tool.latencyMs}ms` : '无'}</dd>
                          <dt>input</dt>
                          <dd>{compact(tool.input)}</dd>
                          <dt>output</dt>
                          <dd>{compact(tool.output)}</dd>
                          <dt>error</dt>
                          <dd>{compact(tool.error)}</dd>
                        </dl>
                      </article>
                    ))}
                  </div>
                </section>
              </div>
            </section>
          ))
        )}
      </div>
    </div>
  )
}

function DemoPanel() {
  return (
    <div className="b3-module">
      <div className="b3-head">
        <div>
          <span>B3</span>
          <h2>工具调用协议演示</h2>
        </div>
        <div className="b3-summary">
          <span>未接入</span>
        </div>
      </div>
      <p className="b3-empty">演示模式后续接入：粘贴 AIMessage/tool_calls，执行 B3 解析、校验、包装流程。</p>
    </div>
  )
}

export function B3ModuleView({ mode, messages }: B3ModuleViewProps) {
  return mode === 'observe' ? <ObservationPanel messages={messages} /> : <DemoPanel />
}
