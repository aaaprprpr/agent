import { RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { API_BASE } from './appConfig'
import { fetchB4CallDetail, fetchB4Calls } from './backendApi'
import { CodePanel, ModelConfigBar, scopeLabel, stageLabel, StatusMark } from './B4ViewShared'
import type { B4CallDetailResponse, B4CallsResponse } from './types'

type CallsState = {
  payload: B4CallsResponse | null
  error: string | null
  loading: boolean
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
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
        <StatusMark status={detail.call.status} />
        <span>{stageLabel(detail.call.stage)}</span>
        <span>{scopeLabel(detail.call.scope)}</span>
        <span>{detail.call.kind === 'json_object' ? 'JSON object' : 'AIMessage'}</span>
        <span>{detail.call.source}</span>
        <span>{detail.call.mode}</span>
        <span>{detail.call.message_count} messages</span>
        <span>{detail.call.raw_chars} chars</span>
        <span>run {detail.call.run_id}</span>
      </div>
      {error ? <CodePanel title="解析错误" value={error} /> : null}
      <div className="b4-compare-grid">
        <CodePanel title="模型原始输出" value={rawText} />
        <CodePanel
          title={detail.call.kind === 'json_object' ? '解析后的 JSON object' : '标准 AIMessage'}
          value={standardOutput}
        />
      </div>
      <details className="b4-request-details">
        <summary>模型输入与调用信息</summary>
        <div className="b4-compare-grid">
          <CodePanel title="prompt messages" value={promptMessages} muted />
          <CodePanel
            title="调用元数据"
            value={{
              generated_at: detail.call.generated_at,
              roles: detail.call.roles,
              source: detail.call.source,
              mode: detail.call.mode,
              scope: scopeLabel(detail.call.scope),
              artifact: detail.call.id,
            }}
            muted
          />
        </div>
      </details>
    </div>
  )
}

export function B4ObservationPanel({ conversationId }: { conversationId: string | null }) {
  const [callsState, setCallsState] = useState<CallsState>({ payload: null, error: null, loading: true })
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState<B4CallDetailResponse | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const loadCalls = useCallback(async (showLoading = false) => {
    if (showLoading) setCallsState((current) => ({ ...current, loading: true }))
    try {
      const payload = await fetchB4Calls(API_BASE, conversationId)
      setCallsState({ payload, error: null, loading: false })
      setSelectedId((current) => payload.calls.some((call) => call.id === current) ? current : payload.calls[0]?.id ?? '')
    } catch (error) {
      setCallsState((current) => ({ ...current, error: errorMessage(error), loading: false }))
    }
  }, [conversationId])

  useEffect(() => {
    let disposed = false

    async function load() {
      if (document.hidden) return
      try {
        const payload = await fetchB4Calls(API_BASE, conversationId)
        if (disposed) return
        setCallsState({ payload, error: null, loading: false })
        setSelectedId((current) => payload.calls.some((call) => call.id === current) ? current : payload.calls[0]?.id ?? '')
      } catch (error) {
        if (!disposed) setCallsState((current) => ({ ...current, error: errorMessage(error), loading: false }))
      }
    }

    setCallsState({ payload: null, error: null, loading: true })
    setSelectedId('')
    setDetail(null)
    setDetailError(null)
    void load()
    const timer = window.setInterval(load, 5000)
    return () => {
      disposed = true
      window.clearInterval(timer)
    }
  }, [conversationId])

  useEffect(() => {
    let disposed = false
    setDetail(null)
    setDetailError(null)
    if (!selectedId) {
      setDetailLoading(false)
      return () => { disposed = true }
    }

    setDetailLoading(true)
    fetchB4CallDetail(API_BASE, selectedId)
      .then((payload) => {
        if (!disposed) {
          setDetail(payload)
          setDetailLoading(false)
        }
      })
      .catch((error) => {
        if (!disposed) {
          setDetailError(errorMessage(error))
          setDetailLoading(false)
        }
      })
    return () => { disposed = true }
  }, [selectedId])

  const calls = callsState.payload?.calls ?? []
  const metrics = useMemo(() => ({
    total: calls.length,
    success: calls.filter((call) => call.status.toLowerCase().includes('success')).length,
    agentRuntime: calls.filter((call) => call.scope === 'agent_runtime').length,
    memorySupport: calls.filter((call) => call.scope === 'memory_support').length,
  }), [calls])

  return (
    <div className="b4-module">
      <header className="b4-head">
        <div><span>B4</span><h2>Agent LLM决策模块</h2></div>
        <div className="b4-head-actions">
          <span>{conversationId ? `会话 ${conversationId}` : '全局最近调用'}</span>
          <button type="button" title="刷新调用记录" aria-label="刷新调用记录" disabled={callsState.loading} onClick={() => void loadCalls(true)}>
            <RefreshCw size={15} aria-hidden="true" />
          </button>
        </div>
      </header>

      <ModelConfigBar model={callsState.payload?.model} />

      <div className="b4-metrics" aria-label="B4 调用统计">
        <div><span>调用记录</span><strong>{metrics.total}</strong></div>
        <div><span>解析成功</span><strong>{metrics.success}</strong></div>
        <div><span>Agent 主链路</span><strong>{metrics.agentRuntime}</strong></div>
        <div><span>记忆辅助调用</span><strong>{metrics.memorySupport}</strong></div>
      </div>

      {callsState.error ? <p className="b4-error">{callsState.error}</p> : null}
      <nav className="b4-call-strip" aria-label="B4 调用记录">
        {calls.map((call, index) => (
          <button className={selectedId === call.id ? 'active' : ''} type="button" key={call.id} onClick={() => setSelectedId(call.id)}>
            <span>{String(calls.length - index).padStart(2, '0')}</span>
            <strong>{stageLabel(call.stage)}</strong>
            <em>{scopeLabel(call.scope)} · {call.source} / {call.status}</em>
          </button>
        ))}
      </nav>
      {callsState.loading && !callsState.payload ? <p className="b4-empty">正在读取 B4 调用记录...</p> : null}
      {callsState.payload && calls.length === 0 ? (
        <p className="b4-empty">{conversationId ? '当前会话还没有 B4 调用记录。' : '当前还没有可观察的 B4 调用记录。'}</p>
      ) : null}
      {detailError ? <p className="b4-error">{detailError}</p> : null}
      {detailLoading ? <p className="b4-empty">正在读取调用详情...</p> : null}
      {detail && detail.call.id === selectedId ? <CallInspector detail={detail} /> : null}
    </div>
  )
}
