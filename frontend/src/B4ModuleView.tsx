import {
  Bot,
  Braces,
  CheckCircle2,
  Circle,
  Clock3,
  Play,
  Radio,
  XCircle,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { API_BASE } from './appConfig'
import type { ModuleMode } from './appNavigation'
import {
  fetchB4CallDetail,
  fetchB4Calls,
  fetchB4ProtocolCases,
  runB4ProtocolTests,
} from './backendApi'
import { prettyValue } from './moduleViewUtils'
import type {
  B4CallDetailResponse,
  B4CallsResponse,
  B4ProtocolCase,
  B4ProtocolResult,
  B4ProtocolRunResponse,
} from './types'

type B4ModuleViewProps = {
  mode: ModuleMode
  conversationId: string | null
}

const STAGE_LABELS: Record<string, string> = {
  planning: '规划',
  tool_calling: '工具决策',
  observation: '观察',
  answering: '最终回答',
  failure_answering: '失败收束',
  memory_reflection: '记忆反思',
}

function stageLabel(stage: string) {
  return STAGE_LABELS[stage] ?? stage
}

function CodePanel({ title, value, muted = false }: { title: string; value: unknown; muted?: boolean }) {
  return (
    <section className={`b4-code-panel ${muted ? 'is-muted' : ''}`}>
      <h3>{title}</h3>
      <pre>{prettyValue(value)}</pre>
    </section>
  )
}

function CallInspector({ detail }: { detail: B4CallDetailResponse }) {
  const record = detail.record
  const error = record.error
  const promptMessages = record.prompt_messages
  const rawText = record.raw_text
  const standardOutput = detail.standard_output ?? record.parsed_candidate ?? record.parsed_json
  return (
    <div className="b4-inspector">
      <div className="b4-call-meta">
        <span>{stageLabel(detail.call.stage)}</span>
        <span>{detail.call.kind === 'json_object' ? 'JSON object' : 'AIMessage'}</span>
        <span>{detail.call.message_count} messages</span>
        <span>{detail.call.raw_chars} chars</span>
        <span>{detail.call.generated_at || '未记录时间'}</span>
      </div>
      {error ? <CodePanel title="解析错误" value={error} /> : null}
      <div className="b4-compare-grid">
        <CodePanel title="模型原始输出" value={rawText} />
        <CodePanel title={detail.call.kind === 'json_object' ? '解析后的 JSON object' : '标准 AIMessage'} value={standardOutput} />
      </div>
      <details className="b4-request-details">
        <summary>查看实际模型输入</summary>
        <CodePanel title="prompt messages" value={promptMessages} muted />
      </details>
    </div>
  )
}

function ObservationPanel({ conversationId }: { conversationId: string | null }) {
  const [callsState, setCallsState] = useState<{ payload: B4CallsResponse | null; error: string | null }>({ payload: null, error: null })
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState<B4CallDetailResponse | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)

  useEffect(() => {
    let disposed = false
    async function load() {
      try {
        const payload = await fetchB4Calls(API_BASE, conversationId)
        if (disposed) return
        setCallsState({ payload, error: null })
        setSelectedId((current) => payload.calls.some((call) => call.id === current) ? current : payload.calls[0]?.id ?? '')
      } catch (error) {
        if (!disposed) setCallsState({ payload: null, error: error instanceof Error ? error.message : String(error) })
      }
    }
    void load()
    const timer = window.setInterval(load, 1800)
    return () => {
      disposed = true
      window.clearInterval(timer)
    }
  }, [conversationId])

  useEffect(() => {
    let disposed = false
    if (!selectedId) {
      return () => { disposed = true }
    }
    fetchB4CallDetail(API_BASE, selectedId)
      .then((payload) => {
        if (!disposed) {
          setDetail(payload)
          setDetailError(null)
        }
      })
      .catch((error) => {
        if (!disposed) setDetailError(error instanceof Error ? error.message : String(error))
      })
    return () => { disposed = true }
  }, [selectedId])

  const calls = callsState.payload?.calls ?? []
  return (
    <div className="b4-module">
      <header className="b4-head">
        <div><span>B4</span><h2>Agent LLM决策模块</h2></div>
      </header>
      {callsState.error ? <p className="b4-error">{callsState.error}</p> : null}
      <nav className="b4-call-strip" aria-label="B4 调用记录">
        {calls.map((call, index) => (
          <button className={selectedId === call.id ? 'active' : ''} type="button" key={call.id} onClick={() => setSelectedId(call.id)}>
            <span>{String(calls.length - index).padStart(2, '0')}</span>
            <strong>{stageLabel(call.stage)}</strong>
            <em>{call.status}</em>
          </button>
        ))}
      </nav>
      {!callsState.payload && !callsState.error ? <p className="b4-empty">正在读取 B4 调用记录...</p> : null}
      {callsState.payload && calls.length === 0 ? <p className="b4-empty">当前会话还没有可观察的 B4 调用记录。</p> : null}
      {detailError ? <p className="b4-error">{detailError}</p> : null}
      {detail ? <CallInspector detail={detail} /> : null}
    </div>
  )
}

function ResultInspector({ result }: { result: B4ProtocolResult }) {
  const failed = result.test_status !== 'passed'
  return (
    <div className="b4-test-inspector">
      <div className="b4-verdict-row">
        <span className={failed ? 'failed' : 'passed'}>
          {failed ? <XCircle size={14} aria-hidden="true" /> : <CheckCircle2 size={14} aria-hidden="true" />}
          {failed ? '未通过' : '通过'}
        </span>
        <strong>{result.verdict}</strong>
        <em><Clock3 size={13} aria-hidden="true" />{result.elapsed_ms} ms</em>
        {result.stream.delta_count > 0 && <em>{result.stream.delta_count} deltas</em>}
      </div>
      {result.error ? <CodePanel title="错误" value={result.error} /> : null}
      <div className="b4-compare-grid">
        <CodePanel title="模型原始输出" value={result.raw_text || '无原始输出'} />
        <CodePanel title="标准 AIMessage" value={result.ai_message ?? '未生成 AIMessage'} />
      </div>
      <details className="b4-request-details">
        <summary>查看测试输入与实际 prompt</summary>
        <div className="b4-compare-grid">
          <CodePanel title="测试输入" value={result.request} muted />
          <CodePanel title="实际 prompt messages" value={result.prompt_messages} muted />
        </div>
      </details>
      {result.stream.delta_count > 0 && (
        <details className="b4-request-details">
          <summary>查看流式分片</summary>
          <CodePanel title="delta sequence" value={result.stream.deltas} muted />
        </details>
      )}
    </div>
  )
}

function DemoPanel() {
  const [cases, setCases] = useState<B4ProtocolCase[]>([])
  const [selectedCase, setSelectedCase] = useState('content_response')
  const [response, setResponse] = useState<B4ProtocolRunResponse | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let disposed = false
    fetchB4ProtocolCases(API_BASE)
      .then((payload) => {
        if (!disposed) {
          setCases(payload.cases)
          setSelectedCase((current) => payload.cases.some((item) => item.id === current) ? current : payload.cases[0]?.id ?? '')
        }
      })
      .catch((reason) => {
        if (!disposed) setError(reason instanceof Error ? reason.message : String(reason))
      })
    return () => { disposed = true }
  }, [])

  async function run(caseId: string) {
    if (running || !caseId) return
    setRunning(true)
    setError(null)
    try {
      const payload = await runB4ProtocolTests(API_BASE, caseId)
      setResponse(payload)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setRunning(false)
    }
  }

  const activeCase = cases.find((item) => item.id === selectedCase)

  return (
    <div className="b4-module">
      <header className="b4-head">
        <div><span>B4</span><h2>AIMessage 协议合规测试</h2></div>
      </header>
      <div className="b4-demo-layout">
        <aside className="b4-case-panel">
          <h3>测试用例</h3>
          <div className="b4-case-list">
            {cases.map((item) => (
              <button className={selectedCase === item.id ? 'active' : ''} type="button" key={item.id} onClick={() => setSelectedCase(item.id)}>
                {item.kind === 'stream' ? <Radio size={14} aria-hidden="true" /> : item.kind === 'parser' ? <Braces size={14} aria-hidden="true" /> : <Bot size={14} aria-hidden="true" />}
                <span><strong>{item.title}</strong><em>{item.kind}</em></span>
              </button>
            ))}
          </div>
          {activeCase && (
            <div className="b4-case-note">
              <p>{activeCase.description}</p>
              <dl><dt>预期</dt><dd>{activeCase.expected}</dd></dl>
            </div>
          )}
          <div className="b4-run-actions">
            <button className="module-run-button" type="button" disabled={running || !selectedCase} onClick={() => void run(selectedCase)}>
              <Play size={14} aria-hidden="true" />{running ? '运行中' : '运行当前测试'}
            </button>
            <button type="button" disabled={running || cases.length === 0} onClick={() => void run('all')}>运行全部</button>
          </div>
          {error ? <p className="b4-error">{error}</p> : null}
        </aside>
        <main className="b4-demo-result">
          {!response && !running ? <p className="b4-empty">选择测试用例后运行，结果会在这里按 B4 的真实协议链展示。</p> : null}
          {running ? <p className="b4-empty"><Circle size={13} aria-hidden="true" />正在执行 B4 协议测试...</p> : null}
          {response?.results.map((result) => (
            <section className="b4-test-result-section" key={result.case_id}>
              <h3>{cases.find((item) => item.id === result.case_id)?.title ?? result.case_id}</h3>
              <ResultInspector result={result} />
            </section>
          ))}
        </main>
      </div>
    </div>
  )
}

export function B4ModuleView({ mode, conversationId }: B4ModuleViewProps) {
  return mode === 'observe' ? <ObservationPanel conversationId={conversationId} /> : <DemoPanel />
}
