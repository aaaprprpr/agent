import { useMemo, useState } from 'react'
import { CheckCircle, Circle, Wrench, XCircle } from 'lucide-react'

import type { ChatMessage, ToolDetail } from './types'

type ModuleMode = 'observe' | 'demo'

type B2ModuleViewProps = {
  mode: ModuleMode
  messages: ChatMessage[]
}

type B2Execution = {
  id: string
  order: number
  name: string
  status: string
  latencyMs?: number
  input?: unknown
  output?: unknown
  error?: unknown
  raw: string
  messageIndex: number
}

const AVAILABLE_TOOLS = [
  'calculator',
  'current_time',
  'directory_list',
  'file_stat',
  'file_reader',
  'text_file_writer',
  'markdown_file_writer',
  'code_file_writer',
  'json_file_writer',
  'docx_writer',
  'table_file_writer',
  'web_search',
  'local_file_search',
  'table_analyzer',
  'python_sandbox',
]

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

function compact(value: unknown, limit = 82) {
  const text = pretty(value).replace(/\s+/g, ' ').trim()
  if (!text || text === '无') return '无'
  return text.length > limit ? `${text.slice(0, limit)}...` : text
}

function executionFromDetail(detail: ToolDetail, order: number, messageIndex: number, detailIndex: number): B2Execution {
  const parsed = parseJsonObject(detail.body)
  const input = parsed?.input ?? parsed?.args
  const output = parsed?.output
  const error = parsed?.error
  const latency = typeof parsed?.latency_ms === 'number' ? parsed.latency_ms : undefined
  const name =
    typeof parsed?.tool_name === 'string' ? parsed.tool_name
      : typeof parsed?.name === 'string' ? parsed.name
        : toolNameFromLabel(detail.label)
  const status = detail.status || (error ? 'error' : output !== undefined ? 'success' : 'pending')
  return {
    id: `${messageIndex}-${detailIndex}-${order}`,
    order,
    name,
    status,
    latencyMs: latency,
    input: input ?? parsed,
    output,
    error,
    raw: detail.body,
    messageIndex,
  }
}

function collectExecutions(messages: ChatMessage[]) {
  let order = 0
  return messages.flatMap((message, messageIndex) =>
    (message.toolDetails ?? [])
      .map((detail, detailIndex) => ({ detail, detailIndex }))
      .filter(({ detail }) => detail.kind === 'tool')
      .map(({ detail, detailIndex }) => executionFromDetail(detail, ++order, messageIndex, detailIndex)),
  )
}

function statusClass(status: string) {
  const normalized = status.toLowerCase()
  if (normalized.includes('error') || normalized.includes('fail')) return 'error'
  if (normalized.includes('success') || normalized.includes('done')) return 'success'
  return 'pending'
}

function ToolList({ selectedTool, onSelect }: { selectedTool?: string; onSelect?: (tool: string) => void }) {
  return (
    <div className="b2-tool-list">
      {AVAILABLE_TOOLS.map((tool) => (
        <button
          className={tool === selectedTool ? 'active' : ''}
          type="button"
          key={tool}
          onClick={() => onSelect?.(tool)}
        >
          {tool}
        </button>
      ))}
    </div>
  )
}

function ObservationPanel({ messages }: { messages: ChatMessage[] }) {
  const executions = useMemo(() => collectExecutions(messages), [messages])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = executions.find((item) => item.id === selectedId) ?? executions[0]
  const successCount = executions.filter((item) => statusClass(item.status) === 'success').length
  const errorCount = executions.filter((item) => statusClass(item.status) === 'error').length

  return (
    <div className="b2-module">
      <div className="b2-head">
        <div>
          <span>B2</span>
          <h2>Skill工具函数模块</h2>
        </div>
        <div className="b2-summary">
          <span>{executions.length} 次执行</span>
          <span>{successCount} 成功</span>
          <span>{errorCount} 失败</span>
        </div>
      </div>

      <div className="b2-grid">
        <section className="b2-panel">
          <h3>执行时间线</h3>
          <div className="b2-execution-list">
            {executions.length === 0 ? (
              <p className="b2-empty">当前对话还没有可观察的 B2 skill 执行。</p>
            ) : (
              executions.map((item) => {
                const cls = statusClass(item.status)
                return (
                  <button
                    className={`b2-execution-item ${selected?.id === item.id ? 'active' : ''}`}
                    type="button"
                    key={item.id}
                    onClick={() => setSelectedId(item.id)}
                  >
                    <span className={`b2-status ${cls}`}>
                      {cls === 'success' ? <CheckCircle size={14} aria-hidden="true" /> : cls === 'error' ? <XCircle size={14} aria-hidden="true" /> : <Circle size={14} aria-hidden="true" />}
                    </span>
                    <span>
                      <strong>{item.order}. {item.name}</strong>
                      <small>{item.status}{item.latencyMs !== undefined ? ` · ${item.latencyMs}ms` : ''}</small>
                    </span>
                  </button>
                )
              })
            )}
          </div>
        </section>

        <section className="b2-panel b2-detail">
          <h3>调用详情</h3>
          {selected ? (
            <>
              <div className="b2-detail-head">
                <Wrench size={17} aria-hidden="true" />
                <strong>{selected.name}</strong>
                <span className={statusClass(selected.status)}>{selected.status}</span>
              </div>
              <dl className="b2-kv">
                <dt>message</dt>
                <dd>#{selected.messageIndex + 1}</dd>
                <dt>latency</dt>
                <dd>{selected.latencyMs !== undefined ? `${selected.latencyMs}ms` : '无'}</dd>
                <dt>input</dt>
                <dd>{compact(selected.input)}</dd>
                <dt>output</dt>
                <dd>{compact(selected.output)}</dd>
                <dt>error</dt>
                <dd>{compact(selected.error)}</dd>
              </dl>
              <div className="b2-detail-block">
                <h4>Input</h4>
                <pre>{pretty(selected.input)}</pre>
              </div>
              <div className="b2-detail-block">
                <h4>Output</h4>
                <pre>{pretty(selected.output)}</pre>
              </div>
              <div className="b2-detail-block">
                <h4>Error</h4>
                <pre>{pretty(selected.error)}</pre>
              </div>
              <div className="b2-detail-block">
                <h4>Raw</h4>
                <pre>{selected.raw}</pre>
              </div>
            </>
          ) : (
            <p className="b2-empty">选择左侧工具执行后查看详情。</p>
          )}
        </section>

        <section className="b2-panel b2-tools-panel">
          <h3>工具列表</h3>
          <ToolList />
        </section>
      </div>
    </div>
  )
}

function DemoPanel() {
  const [selectedTool, setSelectedTool] = useState(AVAILABLE_TOOLS[0])
  const [args, setArgs] = useState('{\n  "expression": "1 + 1"\n}')

  return (
    <div className="b2-module">
      <div className="b2-head">
        <div>
          <span>B2</span>
          <h2>Skill 单模块演示</h2>
        </div>
        <div className="b2-summary">
          <span>未执行</span>
        </div>
      </div>

      <div className="b2-demo-grid">
        <section className="b2-panel b2-tools-panel">
          <h3>选择工具</h3>
          <ToolList selectedTool={selectedTool} onSelect={setSelectedTool} />
        </section>

        <section className="b2-panel b2-demo-form">
          <h3>构造参数</h3>
          <label>
            tool
            <input value={selectedTool} readOnly />
          </label>
          <label>
            args JSON
            <textarea value={args} onChange={(event) => setArgs(event.target.value)} />
          </label>
          <button type="button" disabled>
            执行工具
          </button>
        </section>

        <section className="b2-panel b2-detail">
          <h3>结果预览</h3>
          <div className="b2-detail-block">
            <h4>Request</h4>
            <pre>{JSON.stringify({ tool_name: selectedTool, args: parseJsonObject(args) ?? args }, null, 2)}</pre>
          </div>
          <p className="b2-empty">后端 demo API 接入后，这里展示 B2 的原始执行结果。</p>
        </section>
      </div>
    </div>
  )
}

export function B2ModuleView({ mode, messages }: B2ModuleViewProps) {
  return mode === 'observe' ? <ObservationPanel messages={messages} /> : <DemoPanel />
}
