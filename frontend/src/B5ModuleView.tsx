import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertCircle,
  Archive,
  Database,
  FileText,
  Play,
  RefreshCw,
  Search,
} from 'lucide-react'

import { API_BASE } from './appConfig'
import { fetchB5MemorySnapshot, runB5RecallPreview } from './backendApi'
import type { B5MemorySnapshot, B5RecallPreviewResponse } from './types'

type ModuleMode = 'observe' | 'demo'

type B5ModuleViewProps = {
  mode: ModuleMode
  conversationId: string | null
}

type SnapshotState = {
  snapshot: B5MemorySnapshot | null
  loading: boolean
  error: string | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

function getString(item: Record<string, unknown> | undefined, key: string, fallback = '无') {
  const value = item?.[key]
  if (value === null || value === undefined || value === '') return fallback
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return fallback
}

function getNumber(item: Record<string, unknown> | undefined, key: string, fallback = 0) {
  const value = item?.[key]
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return fallback
}

function getList(item: Record<string, unknown> | undefined, key: string, limit = 6) {
  const value = item?.[key]
  if (!Array.isArray(value)) return []
  return value.slice(0, limit).map((entry) => String(entry))
}

function compact(value: unknown, limit = 140) {
  const text = typeof value === 'string'
    ? value
    : value === null || value === undefined
      ? ''
      : JSON.stringify(value)
  const normalized = text.replace(/\s+/g, ' ').trim()
  if (!normalized) return '无'
  return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized
}

function boolText(value: unknown) {
  if (value === true) return 'true'
  if (value === false) return 'false'
  return 'unknown'
}

function meaningfulText(value: unknown, limit = 140) {
  const text = compact(value, limit)
  return text === '无' ? '' : text
}

function toolStepEvidence(step: Record<string, unknown>) {
  const output = meaningfulText(step['output'])
  if (output) return `output: ${output}`
  const error = meaningfulText(step['error'])
  if (error) return `error: ${error}`
  const input = meaningfulText(step['input'])
  if (input) return `input: ${input}`
  return ''
}

function JsonBlock({ value, maxHeight = 260 }: { value: unknown; maxHeight?: number }) {
  return (
    <pre className="b5-json" style={{ maxHeight }}>
      {JSON.stringify(value ?? null, null, 2)}
    </pre>
  )
}

function EmptyState({ conversationId }: { conversationId: string | null }) {
  return (
    <div className="b5-empty-state">
      <Database size={20} strokeWidth={1.8} aria-hidden="true" />
      <strong>{conversationId ? '暂无 B5 数据' : '未选择会话'}</strong>
      <p>
        {conversationId
          ? '当前会话还没有可展示的 B5 记忆记录，完成一次主对话后可重新观察。'
          : '请先在左侧选择一个已有会话，或完成一次主对话后再进入 B5 页面。'}
      </p>
    </div>
  )
}

function ErrorState({ message, onRefresh }: { message: string; onRefresh: () => void }) {
  return (
    <div className="b5-error-state">
      <AlertCircle size={18} strokeWidth={1.8} aria-hidden="true" />
      <strong>读取失败</strong>
      <p>{message}</p>
      <button type="button" onClick={onRefresh}>重新读取</button>
    </div>
  )
}

function SnapshotHeader({
  title,
  modeLabel,
  loading,
  onRefresh,
}: {
  title: string
  modeLabel: string
  loading: boolean
  onRefresh: () => void
}) {
  return (
    <header className="b5-head">
      <div>
        <span>B5</span>
        <h2>{title}</h2>
      </div>
      <div className="b5-head-actions">
        <strong>{modeLabel}</strong>
        <button className="b5-refresh-button" type="button" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={14} strokeWidth={1.9} aria-hidden="true" />
          刷新
        </button>
      </div>
    </header>
  )
}

function TurnCompressionView({
  turns,
  summaries,
  blocks,
  messages,
}: {
  turns: Record<string, unknown>[]
  summaries: Record<string, unknown>[]
  blocks: Record<string, unknown>[]
  messages: Record<string, unknown>[]
}) {
  const summariesByTurnId = useMemo(() => {
    const result = new Map<string, Record<string, unknown>>()
    summaries.forEach((summary) => {
      const turnId = getString(summary, 'turn_id', '')
      if (turnId) result.set(turnId, summary)
    })
    return result
  }, [summaries])
  const messagesById = useMemo(() => {
    const result = new Map<string, Record<string, unknown>>()
    messages.forEach((message) => {
      const id = getString(message, 'id', '')
      if (id) result.set(id, message)
    })
    return result
  }, [messages])
  const rowByTurnIndex = useMemo(() => {
    const result = new Map<number, number>()
    turns.forEach((turn, index) => {
      result.set(getNumber(turn, 'turn_index'), index + 2)
    })
    return result
  }, [turns])

  if (turns.length === 0) {
    return <p className="b5-empty">暂无 conversation_turns。完成一次主对话并等待 B5 后台写入后再刷新。</p>
  }

  return (
    <div
      className="b5-compression-board"
      style={{ gridTemplateRows: `34px repeat(${turns.length}, minmax(104px, auto))` }}
    >
      <div className="b5-board-head db">全量数据库</div>
      <div className="b5-board-head turn">轮对话压缩</div>
      <div className="b5-board-head block">块级压缩</div>

      {turns.map((turn) => {
        const turnId = getString(turn, 'id', '')
        const turnIndex = getNumber(turn, 'turn_index')
        const summary = summariesByTurnId.get(turnId)
        const userMessage = messagesById.get(getString(turn, 'user_message_id', ''))
        const assistantMessage = messagesById.get(getString(turn, 'assistant_message_id', ''))
        const toolCount = getNumber(assistantMessage, 'tool_step_count')
        const labels = getList(summary, 'labels')
        return (
          <Fragment key={`turn-${turnId || turnIndex}`}>
            <article
              className="b5-db-turn"
              key={`db-${turnId || turnIndex}`}
              style={{ gridColumn: 1, gridRow: rowByTurnIndex.get(turnIndex) ?? 'auto' }}
            >
              <header>
                <span>turn {turnIndex || '?'}</span>
                <em>{toolCount} tool</em>
              </header>
              <p><strong>用户</strong>{compact(userMessage?.['content'], 140)}</p>
              <p><strong>AI</strong>{compact(assistantMessage?.['content'], 140)}</p>
            </article>

            <article
              className="b5-turn-summary"
              key={`summary-${turnId || turnIndex}`}
              style={{ gridColumn: 2, gridRow: rowByTurnIndex.get(turnIndex) ?? 'auto' }}
            >
              <header>
                <FileText size={14} strokeWidth={1.9} aria-hidden="true" />
                <strong>turn_summary</strong>
                <em>{summary ? getString(summary, 'summary_source') : '暂无'}</em>
              </header>
              {summary ? (
                <>
                  <p>{compact(summary['summary'], 220)}</p>
                  <div className="b5-tags">
                    {labels.length > 0 ? labels.map((label) => <span key={label}>{label}</span>) : <span>no labels</span>}
                  </div>
                </>
              ) : (
                <p className="b5-note">后台 reflection 尚未生成本轮摘要。</p>
              )}
            </article>
          </Fragment>
        )
      })}

      {blocks.map((block) => {
        const start = getNumber(block, 'start_turn_index')
        const end = getNumber(block, 'end_turn_index')
        const startRow = rowByTurnIndex.get(start) ?? 2
        const endRow = (rowByTurnIndex.get(end) ?? startRow) + 1
        return (
          <article
            className="b5-block-card"
            key={getString(block, 'id')}
            style={{ gridColumn: 3, gridRow: `${startRow} / ${endRow}` }}
          >
            <div className="b5-block-range" aria-hidden="true">
              <span />
            </div>
            <div>
              <header>
                <Archive size={14} strokeWidth={1.9} aria-hidden="true" />
                <strong>{getString(block, 'title')}</strong>
              </header>
              <small>turn {start}-{end}</small>
              <p>{compact(block['summary'], 180)}</p>
            </div>
          </article>
        )
      })}

      {blocks.length === 0 && (
        <article className="b5-block-card" style={{ gridColumn: 3, gridRow: `2 / ${turns.length + 2}` }}>
          <div className="b5-block-range" aria-hidden="true">
            <span />
          </div>
          <div>
            <header>
              <Archive size={14} strokeWidth={1.9} aria-hidden="true" />
              <strong>暂无块级压缩</strong>
            </header>
            <small>waiting</small>
            <p>多轮完成并等待 B5 后台反思后，这里会显示真实 memory_blocks。</p>
          </div>
        </article>
      )}
    </div>
  )
}

function TaskMemoryList({ tasks }: { tasks: Record<string, unknown>[] }) {
  if (tasks.length === 0) {
    return <p className="b5-empty">暂无 task_memories。只有 B5 判断为任务状态的轮次才会更新任务记忆。</p>
  }
  return (
    <div className="b5-card-list">
      {tasks.map((task) => (
        <article className="b5-real-card" key={getString(task, 'id')}>
          <header>
            <strong>{getString(task, 'title')}</strong>
            <em>{getString(task, 'status')}</em>
          </header>
          <p>{compact(task['objective'], 180)}</p>
          <dl className="b5-kv">
            <dt>phase</dt>
            <dd>{getString(task, 'phase')}</dd>
            <dt>confidence</dt>
            <dd>{getString(task, 'confidence')}</dd>
          </dl>
          <div className="b5-tags">
            {getList(task, 'next_actions', 4).map((item) => <span key={item}>{item}</span>)}
          </div>
        </article>
      ))}
    </div>
  )
}

function MemoryBlockList({ blocks }: { blocks: Record<string, unknown>[] }) {
  if (blocks.length === 0) {
    return <p className="b5-empty">暂无 memory_blocks。块级压缩通常需要多个已完成 turn。</p>
  }
  return (
    <div className="b5-card-list">
      {blocks.map((block) => (
        <article className="b5-real-card" key={getString(block, 'id')}>
          <header>
            <strong>{getString(block, 'title')}</strong>
            <em>{getString(block, 'status')}</em>
          </header>
          <small>turn {getNumber(block, 'start_turn_index')}-{getNumber(block, 'end_turn_index')}</small>
          <p>{compact(block['summary'], 220)}</p>
          <div className="b5-tags">
            {getList(block, 'keywords', 6).map((item) => <span key={item}>{item}</span>)}
          </div>
        </article>
      ))}
    </div>
  )
}

function RetrievalLogList({ logs }: { logs: Record<string, unknown>[] }) {
  if (logs.length === 0) {
    return <p className="b5-empty">暂无 retrieval log。运行一次 B5 召回演示后会生成真实记录。</p>
  }
  return (
    <div className="b5-card-list">
      {logs.slice(0, 4).map((log) => (
        <article className="b5-real-card" key={getString(log, 'id')}>
          <header>
            <strong>{compact(log['query_text'], 72)}</strong>
            <em>{getString(log, 'created_at')}</em>
          </header>
          <dl className="b5-kv">
            <dt>candidate</dt>
            <dd>{asArray(log['candidate_blocks']).length} blocks</dd>
            <dt>selected</dt>
            <dd>{asArray(log['selected_turns']).length} turns</dd>
            <dt>loaded</dt>
            <dd>{Array.isArray(log['loaded_message_ids']) ? log['loaded_message_ids'].length : 0} messages</dd>
          </dl>
          <JsonBlock value={log['query_context']} maxHeight={150} />
        </article>
      ))}
    </div>
  )
}

function ObservationPanel({
  conversationId,
  state,
  preview,
  onRefresh,
}: {
  conversationId: string | null
  state: SnapshotState
  preview: B5RecallPreviewResponse | null
  onRefresh: () => void
}) {
  const { snapshot, loading, error } = state
  const messages = asArray(snapshot?.messages)
  const turns = asArray(snapshot?.turns)
  const summaries = asArray(snapshot?.turn_summaries)
  const blocks = asArray(snapshot?.memory_blocks)
  const tasks = asArray(snapshot?.task_memories)
  const logs = asArray(snapshot?.retrieval_logs)
  const latestLog = logs[0]
  const latestSelectedTurns = asArray(latestLog?.['selected_turns'])
  const latestCandidateBlocks = asArray(latestLog?.['candidate_blocks'])
  const previewMemoryMessages = asArray(preview?.memory_messages)
  const previewRecentHistory = asArray(preview?.recent_history_messages)
  const previewMemoryText = getString(previewMemoryMessages[0], 'content', '')
  const previewWorkspace = isRecord(preview?.workspace_memory) ? preview.workspace_memory : undefined
  const recallHits = [
    ...tasks.slice(0, 2).map((task) => ({
      key: `task-${getString(task, 'id')}`,
      type: 'task',
      title: getString(task, 'title'),
      score: getString(task, 'confidence', '-'),
      source: getString(task, 'status'),
    })),
    ...latestSelectedTurns.slice(0, 3).map((turn) => ({
      key: `turn-${getString(turn, 'turn_id')}`,
      type: 'turn',
      title: `turn ${getString(turn, 'turn_index')}`,
      score: getString(turn, 'score', '-'),
      source: getString(turn, 'context_role', getString(turn, 'turn_id')),
    })),
    ...latestCandidateBlocks.slice(0, 2).map((block) => ({
      key: `block-${getString(block, 'block_id')}`,
      type: 'block',
      title: getString(block, 'block_id'),
      score: getString(block, 'score', '-'),
      source: `turn ${getString(block, 'start_turn_index')}-${getString(block, 'end_turn_index')}`,
    })),
    ...previewRecentHistory.slice(-2).map((message, index) => ({
      key: `recent-${index}-${getString(message, 'role')}`,
      type: 'recent',
      title: getString(message, 'role'),
      score: 'raw',
      source: compact(message['content'], 72),
    })),
  ]

  return (
    <div className="b5-module">
      <SnapshotHeader
        title="记忆文档存储与查找模块"
        modeLabel="只读观察"
        loading={loading}
        onRefresh={onRefresh}
      />

      {!conversationId ? (
        <EmptyState conversationId={conversationId} />
      ) : error ? (
        <ErrorState message={error} onRefresh={onRefresh} />
      ) : loading && !snapshot ? (
        <p className="b5-loading">正在读取 B5 SQLite 记忆层...</p>
      ) : !snapshot ? (
        <EmptyState conversationId={conversationId} />
      ) : (
        <div className="b5-layout">
          <section className="b5-history-panel" aria-label="历史记录与压缩">
            <div className="b5-panel-title">
              <Database size={15} strokeWidth={1.9} aria-hidden="true" />
              <strong>历史记录与压缩</strong>
            </div>
            <dl className="b5-kv b5-wide-kv">
              <dt>conversation</dt>
              <dd>{snapshot.conversation_id}</dd>
              <dt>status</dt>
              <dd>{snapshot.status}</dd>
              <dt>title</dt>
              <dd>{getString(snapshot.conversation, 'title')}</dd>
            </dl>

            <section className="b5-section">
              <TurnCompressionView turns={turns} summaries={summaries} blocks={blocks} messages={messages} />
            </section>
          </section>

          <section className="b5-recall-panel" aria-label="召回与上下文">
            <div className="b5-panel-title">
              <Search size={15} strokeWidth={1.9} aria-hidden="true" />
              <strong>召回与上下文</strong>
            </div>

            <div className="b5-recall-detail">
              <section className="b5-hit-list">
                <h3>召回内容</h3>
                {recallHits.length === 0 ? (
                  <p className="b5-empty">暂无真实召回命中。运行演示页后会显示最新 retrieval log。</p>
                ) : (
                  recallHits.map((hit) => (
                    <article key={hit.key}>
                      <header>
                        <span>{hit.type}</span>
                        <em>{hit.score}</em>
                      </header>
                      <strong>{hit.title}</strong>
                      <p>{hit.source}</p>
                    </article>
                  ))
                )}
              </section>

              <section className="b5-context-box">
                <h3>拼给 B1 的上下文</h3>
                <div className="b5-context-meta">
                  <span>context_chars {getString(previewWorkspace, 'context_chars', '-')}</span>
                  <span>truncated {boolText(previewWorkspace?.['truncated'])}</span>
                  <span>retrieval logs {snapshot.counts.retrieval_logs ?? 0}</span>
                </div>
                {previewMemoryText ? (
                  <pre>{previewMemoryText}</pre>
                ) : previewRecentHistory.length > 0 ? (
                  <pre>{previewRecentHistory.map((message) => `${getString(message, 'role')}: ${compact(message['content'], 160)}`).join('\n')}</pre>
                ) : latestLog ? (
                  <JsonBlock value={latestLog['query_context']} maxHeight={260} />
                ) : (
                  <p className="b5-empty">演示页运行一次真实召回后，这里会显示本次 memory_messages。</p>
                )}
              </section>
            </div>

            <section className="b5-section">
              <h3>task_memories</h3>
              <TaskMemoryList tasks={tasks} />
            </section>

            <section className="b5-section">
              <h3>memory_blocks</h3>
              <MemoryBlockList blocks={blocks} />
            </section>

            <section className="b5-section">
              <h3>latest retrieval logs</h3>
              <RetrievalLogList logs={logs} />
            </section>
          </section>
        </div>
      )}
    </div>
  )
}

function PreviewResult({ preview }: { preview: B5RecallPreviewResponse }) {
  const workspace = isRecord(preview.workspace_memory) ? preview.workspace_memory : {}
  const recentHistory = asArray(preview.recent_history_messages)
  const memoryMessages = asArray(preview.memory_messages)
  const recalledBlocks = asArray(preview.recalled_blocks)
  const recalledTurns = asArray(preview.recalled_turns)
  const sourceMessages = asArray(preview.source_messages)
  const sourceToolSteps = asArray(preview.source_tool_steps)
  const meaningfulSourceToolSteps = sourceToolSteps
    .map((step) => ({ step, evidence: toolStepEvidence(step) }))
    .filter((item) => item.evidence)
  const memoryText = getString(memoryMessages[0], 'content', '')

  return (
    <div className="b5-preview-result">
      <section className="b5-demo-card">
        <h3>本次 B5 召回状态</h3>
        <dl className="b5-kv">
          <dt>status</dt>
          <dd>{preview.status}</dd>
          <dt>context</dt>
          <dd>{getString(workspace, 'context_chars')} / {getString(workspace, 'max_context_chars')}</dd>
          <dt>truncated</dt>
          <dd>{boolText(workspace['truncated'])}</dd>
          <dt>loaded</dt>
          <dd>{getList(workspace, 'loaded_message_ids', 20).length} messages, {getList(workspace, 'loaded_tool_step_ids', 20).length} tool steps</dd>
          <dt>recent</dt>
          <dd>{recentHistory.length} raw messages</dd>
        </dl>
        <JsonBlock value={{
          vector_retrieval: preview.vector_retrieval,
          llm_rerank: preview.llm_rerank,
          retrieval_log: preview.retrieval_log,
        }} maxHeight={220} />
      </section>

      <section className="b5-demo-card">
        <h3>近期原文历史</h3>
        {recentHistory.length === 0 ? (
          <p className="b5-empty">本次 B5 返回中没有 recent_history_messages。</p>
        ) : (
          <div className="b5-card-list">
            {recentHistory.map((message, index) => (
              <article className="b5-mini-card" key={`${getString(message, 'role')}-${index}`}>
                <span>{getString(message, 'role')}</span>
                <p>{compact(message['content'], 180)}</p>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="b5-demo-card">
        <h3>拼给 B1 的 memory_messages</h3>
        {memoryText ? <pre>{memoryText}</pre> : <p className="b5-empty">本次没有额外生成 memory_messages；如果近期原文历史已有足够信息，这是正常情况。</p>}
      </section>

      <section className="b5-demo-card">
        <h3>召回命中</h3>
        <div className="b5-mini-columns">
          <div>
            <strong>recent_history {recentHistory.length}</strong>
            {recentHistory.length === 0 ? <p className="b5-note">无近期原文历史。</p> : recentHistory.map((message, index) => (
              <article className="b5-mini-card" key={`recent-${index}`}>
                <span>{getString(message, 'role')}</span>
                <p>{compact(message['content'], 120)}</p>
              </article>
            ))}
          </div>
          <div>
            <strong>blocks {recalledBlocks.length}</strong>
            {recalledBlocks.length === 0 ? <p className="b5-note">无 block 命中。</p> : recalledBlocks.map((block) => (
              <article className="b5-mini-card" key={getString(block, 'id')}>
                <span>{getString(block, 'title')}</span>
                <em>{getString(block, 'score')}</em>
                <p>{compact(block['summary'], 120)}</p>
              </article>
            ))}
          </div>
          <div>
            <strong>turns {recalledTurns.length}</strong>
            {recalledTurns.length === 0 ? <p className="b5-note">无 turn 命中。</p> : recalledTurns.map((turn) => (
              <article className="b5-mini-card" key={getString(turn, 'turn_id')}>
                <span>turn {getString(turn, 'turn_index')}</span>
                <em>{getString(turn, 'score')}</em>
                <p>{compact(turn['summary'], 120)}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="b5-demo-card">
        <h3>源证据</h3>
        <div className="b5-mini-columns">
          <div>
            <strong>source_messages {sourceMessages.length}</strong>
            {sourceMessages.length === 0 ? <p className="b5-note">未加载源消息。</p> : sourceMessages.map((message) => (
              <article className="b5-mini-card" key={getString(message, 'message_id')}>
                <span>{getString(message, 'role')}</span>
                <p>{compact(message['content'], 140)}</p>
              </article>
            ))}
          </div>
          <div>
            <strong>source_tool_steps {sourceToolSteps.length}</strong>
            {sourceToolSteps.length === 0 ? <p className="b5-note">未加载源工具步骤。</p> : meaningfulSourceToolSteps.length === 0 ? (
              <p className="b5-note">已加载源工具步骤，但本次没有有效 input / output / error；事实证据主要来自 source_messages。</p>
            ) : meaningfulSourceToolSteps.map(({ step, evidence }) => (
              <article className="b5-mini-card" key={getString(step, 'tool_step_id')}>
                <span>{getString(step, 'tool_name')}</span>
                <em>{getString(step, 'status')}</em>
                <p>{evidence}</p>
              </article>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}

function DemoPanel({
  conversationId,
  state,
  preview,
  onPreview,
  onRefresh,
}: {
  conversationId: string | null
  state: SnapshotState
  preview: B5RecallPreviewResponse | null
  onPreview: (preview: B5RecallPreviewResponse | null) => void
  onRefresh: () => Promise<void>
}) {
  const messages = asArray(state.snapshot?.messages)
  const suggestedInput = useMemo(() => {
    const lastUser = [...messages].reverse().find((message) => getString(message, 'role', '') === 'user')
    return getString(lastUser, 'content', '继续当前任务，读取相关历史上下文。')
  }, [messages])
  const [query, setQuery] = useState('')
  const [queryTouched, setQueryTouched] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setQuery('')
    setQueryTouched(false)
    setError(null)
  }, [conversationId])

  useEffect(() => {
    if (!queryTouched && suggestedInput) setQuery(suggestedInput)
  }, [queryTouched, suggestedInput])

  async function handleRunPreview() {
    if (!conversationId || !query.trim() || running) return
    setRunning(true)
    setError(null)
    try {
      const result = await runB5RecallPreview(API_BASE, conversationId, query.trim())
      onPreview(result)
      await onRefresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="b5-module">
      <SnapshotHeader
        title="B5 真实召回演示"
        modeLabel="真实运行"
        loading={state.loading}
        onRefresh={() => {
          void onRefresh()
        }}
      />

      {!conversationId ? (
        <EmptyState conversationId={conversationId} />
      ) : (
        <div className="b5-demo-grid">
          <section className="b5-demo-card">
            <h3>构造召回输入</h3>
            <p className="b5-note">点击运行会真实调用 B5 prepare_workspace_memory_context，并写入一次 retrieval log。</p>
            <label>
              conversation_id
              <input value={conversationId} readOnly />
            </label>
            <label>
              current_user_input
              <textarea
                value={query}
                onChange={(event) => {
                  setQueryTouched(true)
                  setQuery(event.target.value)
                }}
              />
            </label>
            <button type="button" disabled={running || !query.trim()} onClick={handleRunPreview}>
              <Play size={14} strokeWidth={1.9} aria-hidden="true" />
              {running ? '运行中' : '运行 B5 召回'}
            </button>
            {error && <p className="b5-error-text">{error}</p>}
          </section>

          <section className="b5-demo-card">
            <h3>输入预览</h3>
            <JsonBlock value={{
              operation: 'prepare_workspace_memory_context',
              conversation_id: conversationId,
              current_user_input: query,
              history_messages: state.snapshot?.counts.messages ?? 0,
              turns: state.snapshot?.counts.turns ?? 0,
              memory_blocks: state.snapshot?.counts.memory_blocks ?? 0,
            }} maxHeight={280} />
          </section>

          {preview ? (
            <PreviewResult preview={preview} />
          ) : (
            <section className="b5-demo-card b5-demo-placeholder">
              <h3>运行结果</h3>
              <p className="b5-empty">尚未运行本页演示。运行后这里会展示真实 workspace_memory、召回结果、源证据和 retrieval log。</p>
            </section>
          )}
        </div>
      )}
    </div>
  )
}

export function B5ModuleView({ mode, conversationId }: B5ModuleViewProps) {
  const [state, setState] = useState<SnapshotState>({
    snapshot: null,
    loading: false,
    error: null,
  })
  const [preview, setPreview] = useState<B5RecallPreviewResponse | null>(null)

  const refreshSnapshot = useCallback(async () => {
    if (!conversationId) {
      setState({ snapshot: null, loading: false, error: null })
      setPreview(null)
      return
    }
    setState((current) => ({ ...current, loading: true, error: null }))
    try {
      const snapshot = await fetchB5MemorySnapshot(API_BASE, conversationId)
      setState({ snapshot, loading: false, error: null })
    } catch (err) {
      setState((current) => ({
        snapshot: current.snapshot,
        loading: false,
        error: err instanceof Error ? err.message : String(err),
      }))
    }
  }, [conversationId])

  useEffect(() => {
    void refreshSnapshot()
  }, [refreshSnapshot])

  return mode === 'observe' ? (
    <ObservationPanel conversationId={conversationId} state={state} preview={preview} onRefresh={refreshSnapshot} />
  ) : (
    <DemoPanel
      conversationId={conversationId}
      state={state}
      preview={preview}
      onPreview={setPreview}
      onRefresh={refreshSnapshot}
    />
  )
}
