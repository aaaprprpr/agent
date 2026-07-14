import { CheckCircle2, Circle, Clock3, Play, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { API_BASE } from './appConfig'
import { fetchB4ProtocolCases, runB4ProtocolTests } from './backendApi'
import { CaseKindIcon, CodePanel, kindLabel, ModelConfigBar } from './B4ViewShared'
import type { B4ProtocolCase, B4ProtocolResult, B4ProtocolRunResponse, B4ProtocolCasesResponse } from './types'

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
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
        <summary>输入、tools_schema 与实际 prompt</summary>
        <div className="b4-compare-grid">
          <CodePanel title="验证输入" value={result.request} muted />
          <CodePanel title="实际 prompt messages" value={result.prompt_messages} muted />
        </div>
      </details>
      {result.stream.delta_count > 0 && (
        <details className="b4-request-details">
          <summary>流式分片</summary>
          <CodePanel title="delta sequence" value={result.stream.deltas} muted />
        </details>
      )}
    </div>
  )
}

function RunSummary({ response }: { response: B4ProtocolRunResponse }) {
  return (
    <div className="b4-run-summary">
      <div><span>本次验证</span><strong>{response.summary.total}</strong></div>
      <div><span>通过</span><strong>{response.summary.passed}</strong></div>
      <div><span>未通过</span><strong>{response.summary.failed}</strong></div>
      <div><span>运行编号</span><strong title={response.run_id}>{response.run_id}</strong></div>
    </div>
  )
}

export function B4DemoPanel() {
  const [catalog, setCatalog] = useState<B4ProtocolCasesResponse | null>(null)
  const [selectedCase, setSelectedCase] = useState('content_response')
  const [response, setResponse] = useState<B4ProtocolRunResponse | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let disposed = false
    fetchB4ProtocolCases(API_BASE)
      .then((payload) => {
        if (!disposed) {
          setCatalog(payload)
          setSelectedCase((current) => payload.cases.some((item) => item.id === current) ? current : payload.cases[0]?.id ?? '')
          setError(null)
        }
      })
      .catch((reason) => {
        if (!disposed) setError(errorMessage(reason))
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
      setError(errorMessage(reason))
    } finally {
      setRunning(false)
    }
  }

  const cases: B4ProtocolCase[] = catalog?.cases ?? []
  const activeCase = cases.find((item) => item.id === selectedCase)

  return (
    <div className="b4-module">
      <header className="b4-head">
        <div><span>B4</span><h2>AIMessage 协议验收演示</h2></div>
        <span className="b4-demo-scope">真实模型与解析器</span>
      </header>

      <ModelConfigBar model={catalog?.model} />

      <div className="b4-demo-layout">
        <aside className="b4-case-panel">
          <h3>验收用例</h3>
          <div className="b4-case-list">
            {cases.map((item) => (
              <button className={selectedCase === item.id ? 'active' : ''} type="button" key={item.id} onClick={() => setSelectedCase(item.id)}>
                <CaseKindIcon kind={item.kind} />
                <span><strong>{item.title}</strong><em>{item.level} · {kindLabel(item.kind)}</em></span>
              </button>
            ))}
          </div>
          {activeCase && (
            <div className="b4-case-note">
              <div className="b4-case-tags"><span>{activeCase.level}</span><span>{kindLabel(activeCase.kind)}</span></div>
              <p>{activeCase.description}</p>
              <dl><dt>预期</dt><dd>{activeCase.expected}</dd></dl>
            </div>
          )}
          <div className="b4-run-actions">
            <button className="module-run-button" type="button" disabled={running || !selectedCase} onClick={() => void run(selectedCase)}>
              <Play size={14} aria-hidden="true" />{running ? '执行中' : '执行当前用例'}
            </button>
            <button type="button" title="包含真实模型调用" disabled={running || cases.length === 0} onClick={() => void run('all')}>执行全部用例</button>
          </div>
          {activeCase?.kind !== 'parser' ? (
            <p className="b4-run-note">当前用例会调用模型服务；执行全部还会运行解析器回放。</p>
          ) : (
            <p className="b4-run-note">当前用例不调用模型；执行全部仍包含真实模型调用。</p>
          )}
          {error ? <p className="b4-error">{error}</p> : null}
        </aside>
        <main className="b4-demo-result">
          {response ? <RunSummary response={response} /> : null}
          {!response && !running ? <p className="b4-empty">尚无协议验证结果。</p> : null}
          {running ? <p className="b4-empty"><Circle size={13} aria-hidden="true" />正在执行 B4 协议验证...</p> : null}
          {response?.results.map((result) => (
            <details
              className={`b4-test-result-section ${result.test_status === 'passed' ? 'passed' : 'failed'}`}
              key={result.case_id}
              defaultOpen={result.test_status !== 'passed' || response.results.length === 1}
            >
              <summary>
                <strong>{cases.find((item) => item.id === result.case_id)?.title ?? result.case_id}</strong>
                <span>{result.test_status === 'passed' ? '通过' : '未通过'}</span>
                <em>{result.elapsed_ms} ms</em>
              </summary>
              <ResultInspector result={result} />
            </details>
          ))}
        </main>
      </div>
    </div>
  )
}
