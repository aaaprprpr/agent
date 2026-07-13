import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, CheckCircle, Circle, Play, Wrench, XCircle } from 'lucide-react'

import { API_BASE } from './appConfig'
import { fetchB2Skills, runB2SkillPreview } from './backendApi'
import type { B2SkillDefinition, B2SkillRunResponse, ChatMessage, ToolDetail } from './types'

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

type SkillState = {
  tools: B2SkillDefinition[]
  toolset: string
  loading: boolean
  error: string | null
}

const DEFAULT_TOOLSET = 'basic_tools'

type SkillExample = {
  note: string
  input: Record<string, unknown>
}

const SKILL_EXAMPLES: Record<string, SkillExample> = {
  calculator: {
    note: '计算一个带括号、乘除和幂运算的确定性表达式。',
    input: { expression: '((18 + 24) * 3 - 16) / 5 + 2 ** 3' },
  },
  current_time: {
    note: '读取当前上海时区时间，展示实时工具返回的日期、星期和时间戳字段。',
    input: { timezone: 'Asia/Shanghai' },
  },
  directory_list: {
    note: '列出 data/docs 下的可读文档，展示目录遍历、后缀过滤和条目计数。',
    input: {
      path: 'docs',
      recursive: false,
      max_entries: 20,
      file_types: ['txt', 'md', 'docx', 'pptx'],
    },
  },
  file_stat: {
    note: '检查一个真实 docx 样例，展示路径归一化、文件大小和可读性判断。',
    input: { path: 'docs/sample_agent.docx' },
  },
  file_reader: {
    note: '读取一个 Markdown 样例文件，展示正文抽取、行号和截断状态。',
    input: { path: 'docs/search_skill_demo.md', max_chars: 600 },
  },
  text_file_writer: {
    note: '生成 txt 文件，展示 B2 写文件能力和前端下载入口。',
    input: {
      filename: 'b2_skill_demo/report.txt',
      content: 'B2 Skill 演示报告\n\n- 工具：text_file_writer\n- 行为：生成纯文本文件\n- 验收点：返回 generated_file_path、relative_output_path 和下载入口。',
    },
  },
  markdown_file_writer: {
    note: '生成 Markdown 文件，展示结构化文本写入和 artifact 返回。',
    input: {
      filename: 'b2_skill_demo/skill_notes.md',
      content: '# B2 Skill 演示\n\n## 目标\n展示 markdown_file_writer 能生成 Markdown 文件。\n\n- 输入来自前端 JSON\n- 输出落在 generated_files\n- 页面显示下载入口',
    },
  },
  code_file_writer: {
    note: '生成 Python 代码文件，只写文件不执行代码。',
    input: {
      filename: 'b2_skill_demo/calc_demo.py',
      language: 'python',
      content: 'values = [3, 5, 8]\nprint(sum(value * 2 for value in values))\n',
    },
  },
  json_file_writer: {
    note: '生成 JSON 文件，展示对象序列化能力。',
    input: {
      filename: 'b2_skill_demo/summary.json',
      data: {
        module: 'B2',
        skill: 'json_file_writer',
        checks: ['structured input', 'json serialization', 'artifact output'],
      },
    },
  },
  docx_writer: {
    note: '生成可打开的 Word 文档，展示 docx writer 的最小文档能力。',
    input: {
      filename: 'b2_skill_demo/meeting_note.docx',
      content: 'B2 Skill 演示纪要\n\n本文件由 docx_writer 生成。\n验收重点：文件创建成功、返回字节数、前端可下载。',
    },
  },
  table_file_writer: {
    note: '生成 CSV 表格，展示列名、行数据和文件产物。',
    input: {
      filename: 'b2_skill_demo/metrics.csv',
      columns: ['skill', 'status', 'latency_ms'],
      rows: [
        { skill: 'calculator', status: 'success', latency_ms: 3.2 },
        { skill: 'file_reader', status: 'success', latency_ms: 12.5 },
        { skill: 'web_search', status: 'pending', latency_ms: '' },
      ],
    },
  },
  web_search: {
    note: '执行一次真实联网搜索；如果网络或 DDGS 不可用，会如实返回 error。',
    input: {
      query: '人工智能 Agent 工具调用 最新进展',
      top_k: 3,
      search_type: 'text',
      region: 'cn-zh',
    },
  },
  local_file_search: {
    note: '在 data/docs 文本样例中搜索 Agent/工具/记忆相关内容。',
    input: {
      query: 'Agent 工具调用 记忆',
      root_dir: 'docs',
      file_types: ['txt', 'md'],
      top_k: 5,
      max_file_chars: 20000,
    },
  },
  table_analyzer: {
    note: '分析真实 CSV 表格，展示行列数、预览和数值统计。',
    input: { path: 'tables/results.csv', max_rows_preview: 3, describe: true },
  },
  python_sandbox: {
    note: '在独立沙箱中执行一段轻量 Python 代码，展示 stdout、退出码和诊断信息。',
    input: {
      code: 'values = [3, 5, 8, 13]\nprint("count=", len(values))\nprint("sum=", sum(values))\nprint("max=", max(values))',
      timeout_seconds: 5,
      max_output_chars: 2000,
    },
  },
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

function parseJsonObject(text: string) {
  try {
    const value = JSON.parse(text)
    return isRecord(value) ? value : undefined
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

function getRecordString(value: Record<string, unknown> | undefined, key: string, fallback = '无') {
  const item = value?.[key]
  if (item === undefined || item === null || item === '') return fallback
  if (typeof item === 'string') return item
  if (typeof item === 'number' || typeof item === 'boolean') return String(item)
  return fallback
}

function sampleValue(name: string, schema: Record<string, unknown> | undefined): unknown {
  if (name === 'expression') return '1 + 1'
  if (name === 'query') return 'Agent'
  if (name === 'path') return 'docs/agent_intro.txt'
  if (name === 'root_dir') return 'docs'
  if (name === 'filename') return 'b2_demo.txt'
  if (name === 'content') return 'B2 skill demo output.'
  if (name === 'code') return 'print(1 + 1)'
  if (name === 'columns') return ['name', 'value']
  if (name === 'rows') return [{ name: 'B2', value: 'skill' }]
  if (name === 'data') return { module: 'B2', demo: true }
  const type = schema?.type
  if (type === 'integer') return 1
  if (type === 'number') return 1
  if (type === 'boolean') return false
  if (type === 'array') return []
  if (type === 'object') return {}
  return ''
}

function defaultArgsForTool(tool: B2SkillDefinition | undefined, name: string) {
  if (SKILL_EXAMPLES[name]) return SKILL_EXAMPLES[name].input
  const parameters = tool?.parameters ?? {}
  const required = tool?.required?.length ? tool.required : Object.keys(parameters)
  return required.reduce<Record<string, unknown>>((result, key) => {
    result[key] = sampleValue(key, parameters[key])
    return result
  }, {})
}

function exampleNoteForTool(name: string) {
  return SKILL_EXAMPLES[name]?.note ?? '根据 tools.yaml 参数自动生成的最小示例。'
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
        : typeof parsed?.skill_name === 'string' ? parsed.skill_name
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

function toolByName(tools: B2SkillDefinition[], name: string) {
  return tools.find((tool) => tool.name === name)
}

function resultRecord(response: B2SkillRunResponse | null) {
  return isRecord(response?.result) ? response.result : undefined
}

function artifactHref(downloadUrl: unknown) {
  if (typeof downloadUrl !== 'string' || !downloadUrl) return ''
  return downloadUrl.startsWith('http') ? downloadUrl : `${API_BASE}${downloadUrl}`
}

function ToolList({
  tools,
  selectedTool,
  onSelect,
}: {
  tools: B2SkillDefinition[]
  selectedTool?: string
  onSelect?: (tool: string) => void
}) {
  if (tools.length === 0) {
    return <p className="b2-empty">未读取到 tools.yaml 中的 B2 Skill。</p>
  }
  return (
    <div className="b2-tool-list">
      {tools.map((tool) => (
        <button
          className={tool.name === selectedTool ? 'active' : ''}
          type="button"
          key={tool.name}
          onClick={() => onSelect?.(tool.name)}
        >
          <span>{tool.name}</span>
          {tool.side_effects && <em>side effect</em>}
        </button>
      ))}
    </div>
  )
}

function SkillCatalog({
  state,
  selectedTool,
  onSelect,
}: {
  state: SkillState
  selectedTool?: string
  onSelect?: (tool: string) => void
}) {
  return (
    <>
      {state.error ? (
        <p className="b2-error-text">
          <AlertCircle size={14} aria-hidden="true" />
          {state.error}
        </p>
      ) : state.loading && state.tools.length === 0 ? (
        <p className="b2-empty">正在读取 B2 Skill 清单...</p>
      ) : (
        <ToolList tools={state.tools} selectedTool={selectedTool} onSelect={onSelect} />
      )}
    </>
  )
}

function ObservationPanel({
  messages,
  skills,
}: {
  messages: ChatMessage[]
  skills: SkillState
}) {
  const executions = useMemo(() => collectExecutions(messages), [messages])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = executions.find((item) => item.id === selectedId) ?? executions[0]

  return (
    <div className="b2-module">
      <div className="b2-head">
        <div>
          <span>B2</span>
          <h2>Skill工具函数模块</h2>
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
          <h3>真实 Skill 清单</h3>
          <SkillCatalog state={skills} />
        </section>
      </div>
    </div>
  )
}

function DemoResult({ response }: { response: B2SkillRunResponse | null }) {
  const result = resultRecord(response)
  const output = isRecord(result?.output) ? result.output : undefined
  const error = isRecord(result?.error) ? result.error : undefined
  const summary = isRecord(result?.summary) ? result.summary : undefined
  const artifacts = asArray(result?.artifacts)
  const outputDownloadUrl = artifactHref(output?.download_url)

  if (!response || !result) {
    return <p className="b2-empty">尚未运行本页演示。点击执行后会展示 B2 SkillResult 原始结果。</p>
  }

  return (
    <>
      <div className="b2-detail-head">
        <Wrench size={17} aria-hidden="true" />
        <strong>{response.skill_name}</strong>
        <span className={statusClass(getRecordString(result, 'status'))}>{getRecordString(result, 'status')}</span>
      </div>
      <dl className="b2-kv">
        <dt>run_id</dt>
        <dd>{response.run_id}</dd>
        <dt>latency</dt>
        <dd>{getRecordString(result, 'latency_ms')}ms</dd>
        <dt>summary</dt>
        <dd>{compact(summary?.message)}</dd>
        <dt>artifact</dt>
        <dd>{artifacts.length || outputDownloadUrl ? 'available' : '无'}</dd>
      </dl>
      {outputDownloadUrl && (
        <a className="b2-artifact-link" href={outputDownloadUrl} target="_blank" rel="noreferrer">
          下载 {getRecordString(output, 'filename', '生成文件')}
        </a>
      )}
      {artifacts.map((artifact, index) => {
        const href = artifactHref(artifact.download_url)
        return href ? (
          <a className="b2-artifact-link" href={href} target="_blank" rel="noreferrer" key={`${href}-${index}`}>
            下载 {getRecordString(artifact, 'filename', `artifact ${index + 1}`)}
          </a>
        ) : null
      })}
      <div className="b2-detail-block">
        <h4>Output</h4>
        <pre>{pretty(output)}</pre>
      </div>
      <div className="b2-detail-block">
        <h4>Error</h4>
        <pre>{pretty(error)}</pre>
      </div>
      <div className="b2-detail-block">
        <h4>Raw SkillResult</h4>
        <pre>{pretty(result)}</pre>
      </div>
    </>
  )
}

function DemoPanel({
  skills,
}: {
  skills: SkillState
}) {
  const initialTool = skills.tools[0]?.name ?? 'calculator'
  const [selectedTool, setSelectedTool] = useState(initialTool)
  const selectedDefinition = toolByName(skills.tools, selectedTool)
  const [args, setArgs] = useState(() => JSON.stringify(defaultArgsForTool(selectedDefinition, selectedTool), null, 2))
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [response, setResponse] = useState<B2SkillRunResponse | null>(null)

  useEffect(() => {
    if (skills.tools.length === 0) return
    if (toolByName(skills.tools, selectedTool)) return
    const nextTool = skills.tools[0].name
    setSelectedTool(nextTool)
    setArgs(JSON.stringify(defaultArgsForTool(skills.tools[0], nextTool), null, 2))
  }, [selectedTool, skills.tools])

  function selectTool(name: string) {
    const definition = toolByName(skills.tools, name)
    setSelectedTool(name)
    setArgs(JSON.stringify(defaultArgsForTool(definition, name), null, 2))
    setError(null)
    setResponse(null)
  }

  function resetExample() {
    setArgs(JSON.stringify(defaultArgsForTool(selectedDefinition, selectedTool), null, 2))
    setError(null)
  }

  async function handleRun() {
    if (running) return
    const parsed = parseJsonObject(args)
    if (!parsed) {
      setError('args JSON 必须是一个 JSON object。')
      return
    }
    setRunning(true)
    setError(null)
    try {
      const result = await runB2SkillPreview(API_BASE, selectedTool, parsed, skills.toolset)
      setResponse(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="b2-module">
      <div className="b2-head">
        <div>
          <span>B2</span>
          <h2>Skill 单模块演示</h2>
        </div>
      </div>

      <div className="b2-demo-grid">
        <section className="b2-panel b2-tools-panel">
          <h3>选择工具</h3>
          <SkillCatalog state={skills} selectedTool={selectedTool} onSelect={selectTool} />
        </section>

        <section className="b2-panel b2-demo-form">
          <h3>构造参数</h3>
          <div className="b2-example-note">
            <strong>当前示例</strong>
            <p>{exampleNoteForTool(selectedTool)}</p>
            <button type="button" onClick={resetExample}>恢复示例 JSON</button>
          </div>
          <label>
            tool
            <input value={selectedTool} readOnly />
          </label>
          <label>
            args JSON
            <textarea value={args} onChange={(event) => setArgs(event.target.value)} />
          </label>
          <button className="b2-run-button" type="button" disabled={running || !selectedTool} onClick={handleRun}>
            <Play size={14} aria-hidden="true" />
            {running ? '执行中' : '执行 B2 Skill'}
          </button>
          {selectedDefinition && (
            <div className="b2-detail-block">
              <h4>Skill contract</h4>
              <pre>{pretty({
                description: selectedDefinition.description,
                side_effects: selectedDefinition.side_effects,
                parameters: selectedDefinition.parameters,
                required: selectedDefinition.required,
                returns: selectedDefinition.returns,
              })}</pre>
            </div>
          )}
          {error && <p className="b2-error-text"><AlertCircle size={14} aria-hidden="true" />{error}</p>}
        </section>

        <section className="b2-panel b2-detail">
          <h3>真实执行结果</h3>
          <div className="b2-detail-block">
            <h4>Request</h4>
            <pre>{JSON.stringify({ skill_name: selectedTool, input: parseJsonObject(args) ?? args, toolset: skills.toolset }, null, 2)}</pre>
          </div>
          <DemoResult response={response} />
        </section>
      </div>
    </div>
  )
}

export function B2ModuleView({ mode, messages }: B2ModuleViewProps) {
  const [skills, setSkills] = useState<SkillState>({
    tools: [],
    toolset: DEFAULT_TOOLSET,
    loading: false,
    error: null,
  })

  async function loadSkills() {
    setSkills((current) => ({ ...current, loading: true, error: null }))
    try {
      const payload = await fetchB2Skills(API_BASE, DEFAULT_TOOLSET)
      setSkills({
        tools: payload.tools ?? [],
        toolset: payload.toolset || DEFAULT_TOOLSET,
        loading: false,
        error: null,
      })
    } catch (err) {
      setSkills((current) => ({
        ...current,
        loading: false,
        error: err instanceof Error ? err.message : String(err),
      }))
    }
  }

  useEffect(() => {
    void loadSkills()
  }, [])

  return mode === 'observe' ? (
    <ObservationPanel messages={messages} skills={skills} />
  ) : (
    <DemoPanel skills={skills} />
  )
}
