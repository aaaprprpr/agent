import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, ArrowLeftRight, ArrowRight, CheckCircle, Circle, FileText, Play, RefreshCw, XCircle } from 'lucide-react'

import { API_BASE } from './appConfig'
import type { ModuleMode } from './appNavigation'
import { fetchB3ToolsSchema, runB3ToolCallsPreview } from './backendApi'
import { B3_EXAMPLES } from './B3ModuleExamples'
import {
  artifactHref as makeArtifactHref,
  asRecordArray as asArray,
  compactValue as compact,
  getRecordString,
  isRecord,
  parseJsonObject,
  prettyValue as pretty,
  statusClass,
  toolNameFromLabel,
} from './moduleViewUtils'
import type { B3ToolCallsPreviewResponse, B3ToolsSchemaResponse, ChatMessage, ToolDetail } from './types'

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

type SchemaState = {
  payload: B3ToolsSchemaResponse | null
  loading: boolean
  error: string | null
}

const DEFAULT_TOOLSET = 'basic_tools'

function schemaName(schema: Record<string, unknown>) {
  const fn = isRecord(schema['function']) ? schema['function'] : undefined
  return getRecordString(fn, 'name')
}

function schemaParameters(schema: Record<string, unknown>) {
  const fn = isRecord(schema['function']) ? schema['function'] : undefined
  const params = isRecord(fn?.parameters) ? fn.parameters : undefined
  const properties = isRecord(params?.properties) ? params.properties : {}
  return Object.keys(properties)
}

function artifactHref(downloadUrl: unknown) {
  return makeArtifactHref(downloadUrl, API_BASE)
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
        : typeof parsed?.skill_name === 'string' ? parsed.skill_name
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

function SchemaPanel({
  state,
  onRefresh,
}: {
  state: SchemaState
  onRefresh: () => void
}) {
  const schemas = state.payload?.tools_schema ?? []
  return (
    <section className="b3-panel b3-schema-panel">
      <div className="b3-panel-toolbar">
        <h3>真实 tools schema</h3>
        <button type="button" onClick={onRefresh} disabled={state.loading}>
          <RefreshCw size={13} aria-hidden="true" />
          刷新
        </button>
      </div>
      {state.error ? (
        <p className="b3-error-text"><AlertCircle size={14} aria-hidden="true" />{state.error}</p>
      ) : state.loading && schemas.length === 0 ? (
        <p className="b3-empty">正在读取 B3 tools schema...</p>
      ) : (
        <>
          <div className="b3-schema-meta">
            <span>{state.payload?.toolset ?? DEFAULT_TOOLSET}</span>
            <span>{schemas.length} tools</span>
          </div>
          <div className="b3-schema-list">
            {schemas.slice(0, 8).map((schema, index) => (
              <article key={`${schemaName(schema)}-${index}`}>
                <strong>{schemaName(schema)}</strong>
                <p>{schemaParameters(schema).slice(0, 6).join(', ') || '无参数'}</p>
              </article>
            ))}
          </div>
          {schemas.length > 8 && <p className="b3-note">仅预览前 8 个 schema；完整 JSON 会在演示结果中展示。</p>}
        </>
      )}
    </section>
  )
}

function ObservationPanel({
  messages,
  schema,
  onRefreshSchema,
}: {
  messages: ChatMessage[]
  schema: SchemaState
  onRefreshSchema: () => void
}) {
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
          <span>{schema.payload?.tool_count ?? 0} schemas</span>
        </div>
      </div>

      <div className="b3-observe-grid">
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

        <SchemaPanel state={schema} onRefresh={onRefreshSchema} />
      </div>
    </div>
  )
}

function ResultCard({ item }: { item: Record<string, unknown> }) {
  const skillResult = isRecord(item.skill_result) ? item.skill_result : undefined
  const output = isRecord(skillResult?.output) ? skillResult.output : undefined
  const error = isRecord(skillResult?.error) ? skillResult.error : undefined
  const summary = isRecord(skillResult?.summary) ? skillResult.summary : undefined
  const artifacts = asArray(skillResult?.artifacts)
  const outputHref = artifactHref(output?.download_url)
  const status = getRecordString(item, 'status', getRecordString(skillResult, 'status', 'unknown'))

  return (
    <article className="b3-result-card">
      <header>
        <span className={statusClass(status)}>
          <StatusIcon status={status} />
        </span>
        <strong>{getRecordString(item, 'name')}</strong>
        <em>{status}</em>
      </header>
      <dl className="b3-kv">
        <dt>tool_call_id</dt>
        <dd>{getRecordString(item, 'tool_call_id')}</dd>
        <dt>latency</dt>
        <dd>{getRecordString(skillResult, 'latency_ms')}ms</dd>
        <dt>summary</dt>
        <dd>{compact(summary?.message)}</dd>
        <dt>error</dt>
        <dd>{compact(error)}</dd>
      </dl>
      {outputHref && (
        <a className="b3-artifact-link" href={outputHref} target="_blank" rel="noreferrer">
          下载 {getRecordString(output, 'filename', '生成文件')}
        </a>
      )}
      {artifacts.map((artifact, index) => {
        const href = artifactHref(artifact.download_url)
        return href ? (
          <a className="b3-artifact-link" href={href} target="_blank" rel="noreferrer" key={`${href}-${index}`}>
            下载 {getRecordString(artifact, 'filename', `artifact ${index + 1}`)}
          </a>
        ) : null
      })}
      <div className="b3-detail-block">
        <h4>SkillResult</h4>
        <pre>{pretty(skillResult)}</pre>
      </div>
    </article>
  )
}

function DemoResult({ response }: { response: B3ToolCallsPreviewResponse | null }) {
  if (!response) {
    return <p className="b3-empty">尚未运行本页演示。运行后会展示真实 ToolMessage、SkillResult、schema 和输出目录。</p>
  }
  const results = asArray(response.results)
  const summary = response.summary ?? {}
  return (
    <>
      <div className="b3-result-summary">
        <span>run_id: {response.run_id}</span>
        <span>tool_calls: {getRecordString(summary, 'tool_call_count')}</span>
        <span>success: {getRecordString(summary, 'success_count')}</span>
        <span>error: {getRecordString(summary, 'error_count')}</span>
      </div>
      <div className="b3-result-list">
        {results.map((item, index) => (
          <ResultCard item={item} key={`${getRecordString(item, 'tool_call_id')}-${index}`} />
        ))}
      </div>
      <div className="b3-detail-block">
        <h4>ToolMessages</h4>
        <pre>{pretty(response.tool_messages)}</pre>
      </div>
      <div className="b3-detail-block">
        <h4>本次 tools_schema</h4>
        <pre>{pretty(response.tools_schema)}</pre>
      </div>
    </>
  )
}

function DemoPanel({
  schema,
  onRefreshSchema,
}: {
  schema: SchemaState
  onRefreshSchema: () => void
}) {
  const firstExample = Object.keys(B3_EXAMPLES)[0]
  const [selectedExample, setSelectedExample] = useState(firstExample)
  const [aiMessageText, setAiMessageText] = useState(() => JSON.stringify(B3_EXAMPLES[firstExample].aiMessage, null, 2))
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [response, setResponse] = useState<B3ToolCallsPreviewResponse | null>(null)

  function selectExample(key: string) {
    const example = B3_EXAMPLES[key]
    if (!example) return
    setSelectedExample(key)
    setAiMessageText(JSON.stringify(example.aiMessage, null, 2))
    setError(null)
    setResponse(null)
  }

  async function handleRun() {
    if (running) return
    const parsed = parseJsonObject(aiMessageText)
    if (!parsed) {
      setError('AIMessage JSON 必须是一个 JSON object。')
      return
    }
    if (!Array.isArray(parsed.tool_calls)) {
      setError('AIMessage JSON 必须包含 tool_calls 数组。')
      return
    }
    setRunning(true)
    setError(null)
    try {
      const result = await runB3ToolCallsPreview(API_BASE, parsed, schema.payload?.toolset ?? DEFAULT_TOOLSET)
      setResponse(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="b3-module">
      <div className="b3-head">
        <div>
          <span>B3</span>
          <h2>工具调用协议演示</h2>
        </div>
        <div className="b3-summary">
          <span>{schema.payload?.toolset ?? DEFAULT_TOOLSET}</span>
          <span>{schema.payload?.tool_count ?? 0} schemas</span>
          <span>{response ? '已执行' : '未执行'}</span>
        </div>
      </div>

      <div className="b3-demo-grid">
        <section className="b3-panel b3-example-panel">
          <h3>选择 AIMessage 样例</h3>
          <div className="b3-example-list">
            {Object.entries(B3_EXAMPLES).map(([key, example]) => (
              <button
                className={key === selectedExample ? 'active' : ''}
                type="button"
                key={key}
                onClick={() => selectExample(key)}
              >
                <span>{example.label}</span>
                {example.sideEffect && <em>side effect</em>}
              </button>
            ))}
          </div>
          <div className="b3-example-note">
            <strong>{B3_EXAMPLES[selectedExample].label}</strong>
            <p>{B3_EXAMPLES[selectedExample].note}</p>
          </div>
          <div className="b3-inline-schema">
            <div>
              <strong>schema 状态</strong>
              <button type="button" onClick={onRefreshSchema} disabled={schema.loading}>
                <RefreshCw size={13} aria-hidden="true" />
                刷新
              </button>
            </div>
            {schema.error ? (
              <p className="b3-error-text"><AlertCircle size={14} aria-hidden="true" />{schema.error}</p>
            ) : (
              <p>{schema.loading ? '正在读取 schema...' : `${schema.payload?.toolset ?? DEFAULT_TOOLSET} · ${schema.payload?.tool_count ?? 0} 个 tools schema`}</p>
            )}
          </div>
        </section>

        <section className="b3-panel b3-demo-form">
          <h3>构造 tool_calls</h3>
          <label>
            AIMessage JSON
            <textarea value={aiMessageText} onChange={(event) => setAiMessageText(event.target.value)} />
          </label>
          <button className="b3-run-button" type="button" disabled={running} onClick={handleRun}>
            <Play size={14} aria-hidden="true" />
            {running ? '执行中' : '运行 B3 工具调用'}
          </button>
          <p className="b3-note">
            本页不会调用 B4 模型；点击运行会真实调用 B3 execute_tool_calls。文件生成或代码沙箱样例会产生本次 demo 输出。
          </p>
          {error && <p className="b3-error-text"><AlertCircle size={14} aria-hidden="true" />{error}</p>}
          <div className="b3-detail-block">
            <h4>请求预览</h4>
            <pre>{pretty({ ai_message: parseJsonObject(aiMessageText) ?? aiMessageText, toolset: schema.payload?.toolset ?? DEFAULT_TOOLSET })}</pre>
          </div>
        </section>

        <section className="b3-panel b3-demo-result">
          <h3>真实 B3 返回</h3>
          <div className="b3-flow-mini">
            <span><FileText size={14} aria-hidden="true" />AIMessage</span>
            <ArrowRight size={14} aria-hidden="true" />
            <span>B3 校验/执行</span>
            <ArrowRight size={14} aria-hidden="true" />
            <span>ToolMessage</span>
          </div>
          <DemoResult response={response} />
        </section>
      </div>
    </div>
  )
}

export function B3ModuleView({ mode, messages }: B3ModuleViewProps) {
  const [schema, setSchema] = useState<SchemaState>({
    payload: null,
    loading: false,
    error: null,
  })

  async function loadSchema() {
    setSchema((current) => ({ ...current, loading: true, error: null }))
    try {
      const payload = await fetchB3ToolsSchema(API_BASE, DEFAULT_TOOLSET)
      setSchema({ payload, loading: false, error: null })
    } catch (err) {
      setSchema((current) => ({
        ...current,
        loading: false,
        error: err instanceof Error ? err.message : String(err),
      }))
    }
  }

  useEffect(() => {
    void loadSchema()
  }, [])

  return mode === 'observe' ? (
    <ObservationPanel messages={messages} schema={schema} onRefreshSchema={() => void loadSchema()} />
  ) : (
    <DemoPanel schema={schema} onRefreshSchema={() => void loadSchema()} />
  )
}
