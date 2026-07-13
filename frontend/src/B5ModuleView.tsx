import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertCircle,
  Archive,
  Database,
  FileText,
  Play,
  Search,
  Upload,
} from 'lucide-react'

import { API_BASE } from './appConfig'
import type { ModuleMode } from './appNavigation'
import { fetchB5MemorySnapshot, runB5RecallPreview } from './backendApi'
import {
  asRecordArray as asArray,
  boolText,
  compactValue,
  getRecordList as getList,
  getRecordNumber as getNumber,
  getRecordString as getString,
  isRecord,
} from './moduleViewUtils'
import type { B5MemorySnapshot, B5RecallPreviewResponse } from './types'

type B5ModuleViewProps = {
  mode: ModuleMode
  conversationId: string | null
}

type SnapshotState = {
  snapshot: B5MemorySnapshot | null
  loading: boolean
  error: string | null
}

function compact(value: unknown, limit = 140) {
  return compactValue(value, limit)
}

function JsonBlock({ value, maxHeight }: { value: unknown; maxHeight?: number }) {
  return (
    <pre className="b5-json" style={maxHeight ? { maxHeight, overflow: 'auto' } : undefined}>
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
}: {
  title: string
}) {
  return (
    <header className="b5-head">
      <div>
        <span>B5</span>
        <h2>{title}</h2>
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
    const orderedTurns = [...turns].sort((a, b) => getNumber(b, 'turn_index') - getNumber(a, 'turn_index'))
    orderedTurns.forEach((turn, index) => {
      result.set(getNumber(turn, 'turn_index'), index + 2)
    })
    return result
  }, [turns])
  const displayTurns = useMemo(
    () => [...turns].sort((a, b) => getNumber(b, 'turn_index') - getNumber(a, 'turn_index')),
    [turns],
  )

  if (turns.length === 0) {
    return <p className="b5-empty">暂无对话轮次。完成一次主对话并等待 B5 后台写入后再刷新。</p>
  }

  return (
    <div
      className="b5-compression-board"
      style={{ gridTemplateRows: `34px repeat(${turns.length}, minmax(104px, auto))` }}
    >
      <div className="b5-board-head db">全量数据库</div>
      <div className="b5-board-head turn">轮对话压缩</div>
      <div className="b5-board-head block">块级压缩</div>

      {displayTurns.map((turn) => {
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
                <span>第 {turnIndex || '?'} 轮</span>
                <em>{toolCount} 个工具</em>
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
                <strong>轮次摘要</strong>
              </header>
              {summary ? (
                <>
                  <p>{compact(summary['summary'], 220)}</p>
                  <div className="b5-tags">
                    {labels.length > 0 ? labels.map((label) => <span key={label}>{label}</span>) : <span>无标签</span>}
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
        const endRow = rowByTurnIndex.get(end) ?? startRow
        const topRow = Math.min(startRow, endRow)
        const bottomRow = Math.max(startRow, endRow) + 1
        return (
          <article
            className="b5-block-card"
            key={getString(block, 'id')}
            style={{ gridColumn: 3, gridRow: `${topRow} / ${bottomRow}` }}
          >
            <div className="b5-block-range" aria-hidden="true">
              <span />
            </div>
            <div>
              <header>
                <Archive size={14} strokeWidth={1.9} aria-hidden="true" />
                <strong>{getString(block, 'title')}</strong>
              </header>
              <small>第 {start}-{end} 轮</small>
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
            <small>等待中</small>
            <p>多轮完成并等待 B5 后台反思后，这里会显示真实块级压缩。</p>
          </div>
        </article>
      )}
    </div>
  )
}

function TaskMemoryList({ tasks }: { tasks: Record<string, unknown>[] }) {
  if (tasks.length === 0) {
    return <p className="b5-empty">暂无任务记忆。只有 B5 判断为任务状态的轮次才会更新任务记忆。</p>
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
    return <p className="b5-empty">暂无块级压缩。块级压缩通常需要多个已完成轮次。</p>
  }
  return (
    <div className="b5-card-list">
      {blocks.map((block) => (
        <article className="b5-real-card" key={getString(block, 'id')}>
          <header>
            <strong>{getString(block, 'title')}</strong>
            <em>{getString(block, 'status')}</em>
          </header>
          <small>第 {getNumber(block, 'start_turn_index')}-{getNumber(block, 'end_turn_index')} 轮</small>
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
    return <p className="b5-empty">暂无召回日志。运行一次 B5 召回演示后会生成真实记录。</p>
  }
  return (
    <div className="b5-card-list">
      {logs.slice(0, 4).map((log) => (
        <article className="b5-real-card" key={getString(log, 'id')}>
          <header>
            <strong>{compact(log['query_text'], 72)}</strong>
            <em>{getString(log, 'created_at')}</em>
          </header>
          <div className="b5-log-stats">
            <span>候选 {asArray(log['candidate_blocks']).length} 块</span>
            <span>命中 {asArray(log['selected_turns']).length} 轮</span>
            <span>加载 {Array.isArray(log['loaded_message_ids']) ? log['loaded_message_ids'].length : 0} 条消息</span>
          </div>
          <JsonBlock value={log['query_context']} />
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
            <div className="b5-conversation-meta">
              <div>
                <span>conversation</span>
                <strong>{snapshot.conversation_id}</strong>
              </div>
              <div>
                <span>status</span>
                <strong>{snapshot.status}</strong>
              </div>
              <div>
                <span>title</span>
                <strong>{getString(snapshot.conversation, 'title')}</strong>
              </div>
            </div>

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
                  <JsonBlock value={latestLog['query_context']} />
                ) : (
                  <p className="b5-empty">演示页运行一次真实召回后，这里会显示本次记忆上下文。</p>
                )}
              </section>
            </div>

            <section className="b5-section">
              <h3>任务记忆</h3>
              <TaskMemoryList tasks={tasks} />
            </section>

            <section className="b5-section">
              <h3>块级压缩</h3>
              <MemoryBlockList blocks={blocks} />
            </section>

            <section className="b5-section">
              <h3>最近召回日志</h3>
              <RetrievalLogList logs={logs} />
            </section>
          </section>
        </div>
      )}
    </div>
  )
}

function RecallResult({
  query,
  preview,
  snapshot,
}: {
  query: string
  preview: B5RecallPreviewResponse | null
  snapshot: B5MemorySnapshot | null
}) {
  const workspace = preview && isRecord(preview.workspace_memory) ? preview.workspace_memory : {}
  const latestLog = asArray(snapshot?.retrieval_logs)[0]
  const recentHistory = preview ? asArray(preview.recent_history_messages) : asArray(snapshot?.messages).slice(0, 4)
  const recalledBlocks = preview ? asArray(preview.recalled_blocks) : asArray(latestLog?.['selected_blocks'])
  const recalledTurns = preview ? asArray(preview.recalled_turns) : asArray(latestLog?.['selected_turns'])
  const sourceMessages = preview ? asArray(preview.source_messages) : recentHistory
  const memoryMessages = preview ? asArray(preview.memory_messages) : []
  const memoryText = getString(memoryMessages[0], 'content', '')

  return (
    <section className="b5-demo-result-card">
      <header>
        <Search size={16} strokeWidth={1.9} aria-hidden="true" />
        <div>
          <h3>召回结果</h3>
          <p>{query ? `当前查询：${query}` : '输入查询后运行召回演示。'}</p>
        </div>
      </header>

      <div className="b5-result-meta">
        <span>状态 {preview?.status ?? '未运行'}</span>
        <span>上下文 {getString(workspace, 'context_chars', '-')}</span>
        <span>日志 {snapshot?.counts.retrieval_logs ?? 0}</span>
      </div>

      <div className="b5-result-columns">
        <section>
          <h4>召回到的历史内容</h4>
          {sourceMessages.length === 0 ? (
            <p className="b5-empty">暂无可展示的历史内容。选择有历史消息的会话后再试。</p>
          ) : (
            <div className="b5-card-list">
              {sourceMessages.map((message, index) => (
                <article className="b5-mini-card" key={`${getString(message, 'id', getString(message, 'message_id'))}-${index}`}>
                  <span>{getString(message, 'role')}</span>
                  <p>{compact(message['content'], 190)}</p>
                </article>
              ))}
            </div>
          )}
        </section>

        <section>
          <h4>命中范围</h4>
          <div className="b5-mini-columns">
            <div>
              <strong>轮次 {recalledTurns.length}</strong>
              {recalledTurns.length === 0 ? <p className="b5-note">暂无轮次命中。</p> : recalledTurns.map((turn) => (
                <article className="b5-mini-card" key={getString(turn, 'turn_id')}>
                  <span>第 {getString(turn, 'turn_index')} 轮</span>
                  <p>{compact(turn['summary'], 120)}</p>
                </article>
              ))}
            </div>
            <div>
              <strong>块 {recalledBlocks.length}</strong>
              {recalledBlocks.length === 0 ? <p className="b5-note">暂无块命中。</p> : recalledBlocks.map((block) => (
                <article className="b5-mini-card" key={getString(block, 'id')}>
                  <span>{getString(block, 'title')}</span>
                  <p>{compact(block['summary'], 120)}</p>
                </article>
              ))}
            </div>
          </div>
          {memoryText && (
            <div className="b5-inline-context">
              <h4>拼给 B1 的上下文</h4>
              <pre>{memoryText}</pre>
            </div>
          )}
        </section>
      </div>
    </section>
  )
}

function DemoPanel({
  conversationId,
  state,
  preview,
  previewRunning,
  previewError,
  onRunRecall,
}: {
  conversationId: string | null
  state: SnapshotState
  preview: B5RecallPreviewResponse | null
  previewRunning: boolean
  previewError: string | null
  onRunRecall: (conversationId: string, query: string) => void
}) {
  const messages = asArray(state.snapshot?.messages)
  const conversationOptions = useMemo(() => {
    const options = new Set<string>()
    if (conversationId) options.add(conversationId)
    if (state.snapshot?.conversation_id) options.add(state.snapshot.conversation_id)
    return Array.from(options)
  }, [conversationId, state.snapshot?.conversation_id])
  const suggestedInput = useMemo(() => {
    const lastUser = [...messages].reverse().find((message) => getString(message, 'role', '') === 'user')
    return getString(lastUser, 'content', '继续当前任务，读取相关历史上下文。')
  }, [messages])
  const [selectedConversationId, setSelectedConversationId] = useState(conversationId ?? '')
  const [uploadedSourceName, setUploadedSourceName] = useState('')
  const [query, setQuery] = useState('')
  const [queryTouched, setQueryTouched] = useState(false)

  useEffect(() => {
    setSelectedConversationId(conversationId ?? '')
    setUploadedSourceName('')
    setQuery('')
    setQueryTouched(false)
  }, [conversationId])

  useEffect(() => {
    if (!queryTouched && suggestedInput) setQuery(suggestedInput)
  }, [queryTouched, suggestedInput])

  const hasSource = Boolean(selectedConversationId || uploadedSourceName)

  return (
    <div className="b5-module">
      <SnapshotHeader
        title="B5 记忆演示"
      />

      {!conversationId ? (
        <EmptyState conversationId={conversationId} />
      ) : (
        <div className="b5-demo-workbench">
          <aside className="b5-demo-controls" aria-label="B5 演示输入">
            <section className="b5-demo-card">
              <h3>数据源</h3>
              <label>
                当前会话
                <select
                  value={selectedConversationId}
                  onChange={(event) => setSelectedConversationId(event.target.value)}
                >
                  {conversationOptions.length === 0 ? (
                    <option value="">暂无会话</option>
                  ) : (
                    conversationOptions.map((id) => <option key={id} value={id}>{id}</option>)
                  )}
                </select>
              </label>
              <label className="b5-file-source">
                <span>
                  <Upload size={14} strokeWidth={1.9} aria-hidden="true" />
                  上传会话数据
                </span>
                <input
                  type="file"
                  accept=".json,application/json"
                  onChange={(event) => setUploadedSourceName(event.target.files?.[0]?.name ?? '')}
                />
                {uploadedSourceName && <em>{uploadedSourceName}</em>}
              </label>
            </section>

            <section className="b5-demo-card">
              <h3>测试召回</h3>
              <label>
                召回输入
                <textarea
                  value={query}
                  onChange={(event) => {
                    setQueryTouched(true)
                    setQuery(event.target.value)
                  }}
                />
              </label>
              <button
                type="button"
                disabled={!hasSource || !selectedConversationId || !query.trim() || previewRunning}
                onClick={() => {
                  onRunRecall(selectedConversationId, query)
                }}
              >
                <Play size={14} strokeWidth={1.9} aria-hidden="true" />
                {previewRunning ? '召回中' : '运行召回演示'}
              </button>
              {previewError && <p className="b5-error-text">{previewError}</p>}
            </section>
          </aside>

          <main className="b5-demo-results" aria-label="B5 演示结果">
            <RecallResult query={query} preview={preview} snapshot={state.snapshot} />
          </main>
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
  const [previewRunning, setPreviewRunning] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)

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

  const runRecall = useCallback(async (targetConversationId: string, currentUserInput: string) => {
    const target = targetConversationId.trim()
    const input = currentUserInput.trim()
    if (!target || !input || previewRunning) return
    setPreviewRunning(true)
    setPreviewError(null)
    try {
      const result = await runB5RecallPreview(API_BASE, target, input)
      setPreview(result)
      if (target === conversationId) {
        await refreshSnapshot()
      }
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err))
    } finally {
      setPreviewRunning(false)
    }
  }, [conversationId, previewRunning, refreshSnapshot])

  return mode === 'observe' ? (
    <ObservationPanel conversationId={conversationId} state={state} preview={preview} onRefresh={refreshSnapshot} />
  ) : (
    <DemoPanel
      conversationId={conversationId}
      state={state}
      preview={preview}
      previewRunning={previewRunning}
      previewError={previewError}
      onRunRecall={(targetConversationId, query) => void runRecall(targetConversationId, query)}
    />
  )
}
