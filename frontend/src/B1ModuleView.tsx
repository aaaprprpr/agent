import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEventHandler, ComponentType, KeyboardEventHandler, ReactNode, RefObject } from 'react'
import { Bot, CheckCircle, Database, MessageSquare, User, Wrench } from 'lucide-react'

import { API_BASE } from './appConfig'
import { fetchB1WorkspaceSnapshot } from './backendApi'
import { Composer } from './Composer'
import type { ModuleMode } from './appNavigation'
import type { Attachment, B1RuntimeEvent, ChatMessage, HistoryItem, RunStreamEvent } from './types'
import type { B1WorkspaceSnapshot as B1WorkspaceSnapshotPayload } from './types'

type B1ModuleViewProps = {
  mode: ModuleMode
  messages: ChatMessage[]
  runtimeEvents: B1RuntimeEvent[]
  histories: HistoryItem[]
  conversationId: string | null
  isRunning: boolean
  isStopping: boolean
  attachments: Attachment[]
  dragActive: boolean
  draft: string
  canSend: boolean
  inputRef: RefObject<HTMLTextAreaElement | null>
  fileRef: RefObject<HTMLInputElement | null>
  onDraftChange: (value: string) => void
  onKeyDown: KeyboardEventHandler<HTMLTextAreaElement>
  onFileChange: ChangeEventHandler<HTMLInputElement>
  onRemoveAttachment: (id: number) => void
  onSend: () => void
  onStop: () => void
  promptOpen: boolean
  systemPrompt: string
  onPromptToggle: () => void
  onPromptSave: () => void
  onSystemPromptChange: (value: string) => void
}

type TrackStatus = 'done' | 'running' | 'idle' | 'warning'
type TrackItem = {
  module: string
  title: string
  status: TrackStatus
  signal: string
  metric: string
  Icon: ComponentType<{ size?: number; strokeWidth?: number; 'aria-hidden'?: boolean }>
}

type B1Snapshot = {
  conversation_id: string | null
  title: string | null
  memory_ready: boolean
  memory_context_status: string
  runtime_status: string
  last_user_input: string | null
  last_final_answer: string | null
  checkpoint: string
}

type WorkspaceLoadState = {
  data: B1WorkspaceSnapshotPayload | null
  loading: boolean
  error: string | null
}

type B1GraphActionKind = 'user_to_b1' | 'b1_to_b5' | 'b5_to_b1' | 'b1_to_b4' | 'b4_to_b1' | 'b1_to_tool' | 'tool_to_b1' | 'b1_to_user'

type B1GraphAction = {
  key: string
  kind: B1GraphActionKind
  label: string
  title: string
  description: string
  payload?: unknown
}

const B1_ACTION_PLAY_MS = 1550

const ROLE_LABELS = {
  user: 'HumanMessage',
  assistant: 'AIMessage',
  tool: 'ToolMessage',
} as const

function compactText(text: string | undefined, limit = 140) {
  const normalized = (text ?? '').replace(/\s+/g, ' ').trim()
  if (!normalized) return '空'
  return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized
}

function countToolDetails(messages: ChatMessage[]) {
  return messages.reduce((total, message) => total + (message.toolDetails?.length ?? 0), 0)
}

function collectToolDetails(messages: ChatMessage[]) {
  return messages.flatMap((message, messageIndex) =>
    (message.toolDetails ?? []).map((detail, detailIndex) => ({
      ...detail,
      messageId: message.id,
      messageIndex,
      detailIndex,
    })),
  )
}

function latestMessage(messages: ChatMessage[], role: ChatMessage['role'], includePending = true) {
  return [...messages].reverse().find((message) => message.role === role && (includePending || message.status !== 'pending'))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asArray(value: unknown) {
  return Array.isArray(value) ? value : []
}

function getRecord(value: unknown) {
  return isRecord(value) ? value : {}
}

function getString(item: Record<string, unknown>, key: string, fallback = '无') {
  const value = item[key]
  if (value === null || value === undefined || value === '') return fallback
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return fallback
}

function jsonText(value: unknown) {
  return JSON.stringify(normalizeJsonForDisplay(value), null, 2)
}

function parseJsonString(value: string) {
  const text = value.trim()
  if (!text || (!text.startsWith('{') && !text.startsWith('['))) return value
  try {
    return JSON.parse(text) as unknown
  } catch {
    return value
  }
}

function normalizeJsonForDisplay(value: unknown, key = ''): unknown {
  if (Array.isArray(value)) return value.map((item) => normalizeJsonForDisplay(item))
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([childKey, childValue]) => [
        childKey,
        normalizeJsonForDisplay(childValue, childKey),
      ]),
    )
  }
  if (typeof value === 'string' && key.endsWith('_json')) {
    const parsed = parseJsonString(value)
    return parsed === value ? value : normalizeJsonForDisplay(parsed)
  }
  return value
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="b1-json">{jsonText(value)}</pre>
}

function runtimeEventDescription(event: RunStreamEvent) {
  if (event.type === 'start') return '后端已接收本轮用户输入，并为本轮创建用户消息与待生成的 AI 消息。'
  if (event.type === 'delta') return compactText(event.text, 260)
  if (event.type === 'state') return compactText(event.reason || event.action || event.state, 260)
  if (event.type === 'tool_start') {
    const calls = Array.isArray(event.tool_calls) ? event.tool_calls : []
    return calls.length > 0 ? `B1 发出 ${calls.length} 个工具调用。` : compactText(event.assistant_content, 260)
  }
  if (event.type === 'tool_done') {
    const messages = Array.isArray(event.tool_messages) ? event.tool_messages : []
    return `B1 收到 ${messages.length} 条工具执行结果。`
  }
  if (event.type === 'done') return compactText(event.final_answer, 260)
  return 'message' in event ? event.message : 'B1 收到运行事件。'
}

function actionPayload(record: B1RuntimeEvent) {
  return {
    event_id: record.id,
    received_at: new Date(record.receivedAt).toISOString(),
    ...record.event,
  }
}

function buildB1DemoActions({
  runtimeEvents,
  workspaceState,
}: {
  runtimeEvents: B1RuntimeEvent[]
  workspaceState: WorkspaceLoadState
}) {
  const workspace = getRecord(workspaceState.data?.workspace)
  const memory = getRecord(workspace.memory)
  const actions: B1GraphAction[] = []

  runtimeEvents.forEach((record) => {
    const event = record.event
    if (event.type === 'start') {
      actions.push({
        key: `input:${record.id}`,
        kind: 'user_to_b1',
        label: 'input',
        title: 'B1 接收用户输入',
        description: runtimeEventDescription(event),
        payload: actionPayload(record),
      })
      return
    }
    if (event.type === 'state') {
      actions.push({
        key: `llm-request:${record.id}`,
        kind: 'b1_to_b4',
        label: 'messages',
        title: 'B1 请求 B4 进行决策',
        description: `第 ${event.llm_call_index ?? '?'} 次 LLM 调用，等待模型返回阶段判断。`,
        payload: actionPayload(record),
      })
      actions.push({
        key: `state:${record.id}`,
        kind: 'b4_to_b1',
        label: event.state || 'state',
        title: 'B1 接收 B4 的阶段判断',
        description: runtimeEventDescription(event),
        payload: actionPayload(record),
      })
      return
    }
    if (event.type === 'tool_start') {
      actions.push({
        key: `tool-start:${record.id}`,
        kind: 'b1_to_tool',
        label: 'tool_calls',
        title: 'B1 下发工具调用',
        description: runtimeEventDescription(event),
        payload: actionPayload(record),
      })
      return
    }
    if (event.type === 'tool_done') {
      actions.push({
        key: `tool-done:${record.id}`,
        kind: 'tool_to_b1',
        label: 'ToolMessage',
        title: 'B1 接收工具结果',
        description: runtimeEventDescription(event),
        payload: actionPayload(record),
      })
      return
    }
    if (event.type === 'delta') {
      actions.push({
        key: `delta:${record.id}`,
        kind: 'b4_to_b1',
        label: 'AIMessage',
        title: 'B1 接收 B4 流式输出',
        description: runtimeEventDescription(event),
        payload: actionPayload(record),
      })
      return
    }
    if (event.type === 'done') {
      actions.push({
        key: `final:${record.id}`,
        kind: 'b1_to_user',
        label: 'final',
        title: 'B1 输出最终回复',
        description: runtimeEventDescription(event),
        payload: actionPayload(record),
      })
      return
    }
    actions.push({
      key: `error:${record.id}`,
      kind: 'b4_to_b1',
      label: 'error',
      title: 'B1 接收运行错误',
      description: runtimeEventDescription(event),
      payload: actionPayload(record),
    })

  })

  const startIndex = actions.findIndex((action) => action.kind === 'user_to_b1')
  if (startIndex >= 0 && Object.keys(memory).length > 0) {
    const turnId = runtimeEvents[0]?.id ?? 'none'
    actions.splice(
      startIndex + 1,
      0,
      {
        key: `memory-request:${turnId}`,
        kind: 'b1_to_b5',
        label: 'memory query',
        title: 'B1 请求 B5 组织记忆上下文',
        description: 'B1 将本轮会话标识和用户输入交给 B5，请求可用于当前任务的记忆上下文。',
        payload: { conversation_id: workspaceState.data?.conversation_id ?? null },
      },
      {
        key: `memory-result:${turnId}`,
        kind: 'b5_to_b1',
        label: 'memory context',
        title: 'B1 接收 B5 记忆上下文',
        description: 'B1 已取得本轮可用的历史消息、压缩记忆或召回结果。',
        payload: memory,
      },
    )
  }

  return actions
}

function useB1WorkspaceCheckpoint(
  conversationId: string | null,
  poll = false,
  eventRevision = 0,
  expectedRunId: string | null = null,
) {
  const [state, setState] = useState<WorkspaceLoadState>({ data: null, loading: false, error: null })

  useEffect(() => {
    if (!conversationId) {
      const resetTimer = window.setTimeout(() => setState({ data: null, loading: false, error: null }), 0)
      return () => window.clearTimeout(resetTimer)
    }
    let active = true
    const load = (showLoading: boolean) => {
      if (showLoading) setState((current) => ({ ...current, loading: !current.data, error: null }))
      fetchB1WorkspaceSnapshot(API_BASE, conversationId)
        .then((data) => {
          if (!active) return
          const checkpoint = getRecord(data.checkpoint)
          const outputDir = getString(checkpoint, 'output_dir', '')
          if (expectedRunId && outputDir && !outputDir.includes(expectedRunId)) {
            setState({ data: null, loading: true, error: null })
            return
          }
          setState({ data, loading: false, error: null })
        })
        .catch((error: unknown) => {
          if (active) {
            setState((current) => ({
              data: current.data,
              loading: false,
              error: error instanceof Error ? error.message : String(error),
            }))
          }
        })
    }
    load(true)
    const timer = poll ? window.setInterval(() => load(false), 400) : undefined
    return () => {
      active = false
      if (timer) window.clearInterval(timer)
    }
  }, [conversationId, eventRevision, expectedRunId, poll])

  return state
}

function useB1Observation({
  messages,
  histories,
  conversationId,
  isRunning,
  isStopping,
}: B1ModuleViewProps) {
  return useMemo(() => {
    const userMessages = messages.filter((message) => message.role === 'user')
    const assistantMessages = messages.filter((message) => message.role === 'assistant')
    const toolDetailCount = countToolDetails(messages)
    const lastUser = [...userMessages].reverse()[0]
    const lastAssistant = [...assistantMessages].reverse().find((message) => message.status !== 'pending')
    const currentHistory = histories.find((item) => item.id === conversationId)
    const pendingAssistant = assistantMessages.some((message) => message.status === 'pending')
    const runtimeStatus = isStopping ? '终止中' : isRunning || pendingAssistant ? '运行中' : messages.length > 0 ? '已完成/空闲' : '无对话'
    const toolRoundCount = messages.filter((message) => (message.toolDetails?.length ?? 0) > 0).length
    const memoryReady = Boolean(currentHistory?.memoryReady)
    const inputStatus: TrackStatus = userMessages.length > 0 ? 'done' : 'idle'
    const messageStatus: TrackStatus = messages.length > 0 ? 'done' : 'idle'
    const modelStatus: TrackStatus = isRunning || pendingAssistant ? 'running' : assistantMessages.length > 0 ? 'done' : 'idle'
    const toolStatus: TrackStatus = toolDetailCount > 0 ? 'done' : 'idle'
    const finalStatus: TrackStatus = pendingAssistant ? 'running' : lastAssistant ? 'done' : 'idle'
    const memoryStatus: TrackStatus = memoryReady ? 'done' : conversationId ? 'warning' : 'idle'

    const track = [
      {
        module: 'B1',
        title: '输入门控',
        status: inputStatus,
        signal: 'HumanMessage',
        metric: `${userMessages.length} 条`,
        Icon: User,
      },
      {
        module: 'B5',
        title: '读取 memory',
        status: memoryStatus,
        signal: 'memory context',
        metric: memoryReady ? '已持久化/可读' : conversationId ? '未展开原文' : '无会话',
        Icon: Database,
      },
      {
        module: 'B1',
        title: '消息装配',
        status: messageStatus,
        signal: 'messages buffer',
        metric: `${messages.length} 条`,
        Icon: MessageSquare,
      },
      {
        module: 'B4',
        title: 'LLM 决策',
        status: modelStatus,
        signal: 'AIMessage',
        metric: `${assistantMessages.length} 条`,
        Icon: Bot,
      },
      {
        module: 'B3',
        title: '工具调用解析',
        status: toolStatus,
        signal: 'tool_calls',
        metric: `${toolRoundCount} 轮`,
        Icon: Wrench,
      },
      {
        module: 'B2',
        title: 'Skill 执行',
        status: toolStatus,
        signal: 'ToolMessage',
        metric: `${toolDetailCount} 项`,
        Icon: Wrench,
      },
      {
        module: 'B1',
        title: '状态收束',
        status: finalStatus,
        signal: 'final answer',
        metric: lastAssistant ? '已生成' : '等待',
        Icon: CheckCircle,
      },
      {
        module: 'B5',
        title: '写入记忆',
        status: memoryStatus,
        signal: 'conversation store',
        metric: memoryReady ? 'ready' : 'pending',
        Icon: Database,
      },
    ] satisfies TrackItem[]

    const snapshot = {
      conversation_id: conversationId,
      title: currentHistory?.title ?? null,
      memory_ready: memoryReady,
      memory_context_status: memoryReady ? 'conversation messages/tool steps loaded from B5 store' : 'raw selected memory context is not exposed to this frontend side channel yet',
      runtime_status: runtimeStatus,
      last_user_input: lastUser?.body ?? null,
      last_final_answer: lastAssistant?.body ?? null,
      checkpoint: 'not_loaded_by_frontend_side_channel',
    } satisfies B1Snapshot

    return { track, snapshot, runtimeStatus }
  }, [conversationId, histories, isRunning, isStopping, messages])
}

function WorkspaceSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="b1-workspace-section">
      <h4>{title}</h4>
      {children}
    </section>
  )
}

function RealWorkspaceSnapshot({ state }: { state: WorkspaceLoadState }) {
  const data = state.data
  const workspace = getRecord(data?.workspace)
  const input = getRecord(workspace.input)
  const memory = getRecord(workspace.memory)
  const task = getRecord(workspace.task)
  const tools = getRecord(workspace.tools)
  const draft = getRecord(workspace.draft)
  const final = getRecord(workspace.final)
  const trace = asArray(workspace.trace)
  const runtime = getRecord(data?.runtime)
  const checkpoint = getRecord(data?.checkpoint)

  if (state.loading) {
    return <p className="b1-workspace-note">正在读取 checkpoints 中的 B1 workspace...</p>
  }
  if (state.error) {
    return <p className="b1-workspace-note">workspace 读取失败：{state.error}</p>
  }
  if (!data || data.status === 'missing' || !isRecord(data.workspace)) {
    return <p className="b1-workspace-note">当前会话还没有可读取的 B1 checkpoint，先显示前端旁路快照。</p>
  }

  return (
    <div className="b1-workspace-real">
      <WorkspaceSection title="checkpoint">
        <dl className="b1-kv">
          <dt>状态</dt>
          <dd>{getString(checkpoint, 'status')}</dd>
          <dt>阶段</dt>
          <dd>{getString(checkpoint, 'stage')}</dd>
          <dt>模式</dt>
          <dd>{getString(checkpoint, 'mode')}</dd>
          <dt>输出</dt>
          <dd>{getString(checkpoint, 'output_dir')}</dd>
        </dl>
      </WorkspaceSection>

      <WorkspaceSection title="input">
        <dl className="b1-kv">
          <dt>会话</dt>
          <dd>{getString(input, 'conversation_id')}</dd>
          <dt>输入</dt>
          <dd>{compactText(getString(input, 'user_input'), 220)}</dd>
          <dt>历史</dt>
          <dd>{asArray(input.history_messages).length} 条</dd>
          <dt>图片</dt>
          <dd>{getString(input, 'input_images_count', '0')}</dd>
        </dl>
        <JsonBlock value={input} />
      </WorkspaceSection>

      <WorkspaceSection title="memory">
        <JsonBlock value={memory} />
      </WorkspaceSection>

      <WorkspaceSection title="task / state">
        <dl className="b1-kv">
          <dt>阶段</dt>
          <dd>{getString(task, 'stage')}</dd>
          <dt>目标</dt>
          <dd>{compactText(getString(task, 'user_goal'), 220)}</dd>
          <dt>原因</dt>
          <dd>{compactText(getString(task, 'reason'), 220)}</dd>
        </dl>
        <JsonBlock value={task} />
      </WorkspaceSection>

      <WorkspaceSection title="tools">
        <dl className="b1-kv">
          <dt>调用</dt>
          <dd>{asArray(tools.calls).length} 项</dd>
          <dt>结果</dt>
          <dd>{asArray(tools.results).length} 项</dd>
          <dt>观察</dt>
          <dd>{asArray(tools.observations).length} 条</dd>
          <dt>意图</dt>
          <dd>{compactText(getString(tools, 'last_tool_intent'), 220)}</dd>
        </dl>
        <JsonBlock value={tools} />
      </WorkspaceSection>

      <WorkspaceSection title="draft">
        <JsonBlock value={draft} />
      </WorkspaceSection>

      <WorkspaceSection title="final">
        <JsonBlock value={final} />
      </WorkspaceSection>

      <WorkspaceSection title="trace">
        <dl className="b1-kv">
          <dt>阶段数</dt>
          <dd>{trace.length} 条</dd>
          <dt>schema</dt>
          <dd>{data.tools_schema_count ?? 0} 个 tool</dd>
        </dl>
        <JsonBlock value={trace} />
      </WorkspaceSection>

      <WorkspaceSection title="runtime / selected memory">
        <JsonBlock value={{ runtime, selected_memory: data.selected_memory }} />
      </WorkspaceSection>
    </div>
  )
}

function WorkspaceSnapshot({
  snapshot,
  messages,
  workspaceState,
}: {
  snapshot: B1Snapshot
  messages: ChatMessage[]
  workspaceState: WorkspaceLoadState
}) {
  const toolDetails = collectToolDetails(messages)

  return (
    <div className="b1-workspace">
      <RealWorkspaceSnapshot state={workspaceState} />

      <section className="b1-workspace-section">
        <h4>前端旁路快照</h4>
        <dl className="b1-kv">
          <dt>ID</dt>
          <dd>{snapshot.conversation_id ?? '无'}</dd>
          <dt>标题</dt>
          <dd>{snapshot.title ?? '无'}</dd>
          <dt>状态</dt>
          <dd>{snapshot.runtime_status}</dd>
        </dl>
      </section>

      <section className="b1-workspace-section b1-fallback-section">
        <h4>B5 memory</h4>
        <dl className="b1-kv">
          <dt>ready</dt>
          <dd>{snapshot.memory_ready ? 'true' : 'false'}</dd>
          <dt>context</dt>
          <dd>{snapshot.memory_context_status}</dd>
        </dl>
      </section>

      <section className="b1-workspace-section">
        <h4>B3/B2 中间过程</h4>
        {toolDetails.length === 0 ? (
          <p className="b1-workspace-note">当前会话没有可观察 tool/agent 中间项。</p>
        ) : (
          <div className="b1-workspace-tool-list">
            {toolDetails.map((detail) => (
              <article className="b1-workspace-tool" key={`${detail.messageId}-${detail.detailIndex}`}>
                <header>
                  <strong>{detail.label}</strong>
                  {detail.kind && <em>{detail.kind}</em>}
                  {detail.status && <em>{detail.status}</em>}
                </header>
                <pre>{detail.body}</pre>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="b1-workspace-section">
        <h4>当前轮摘要</h4>
        <article className="b1-workspace-text">
          <span>最后输入</span>
          <p>{compactText(snapshot.last_user_input ?? '', 180)}</p>
        </article>
        <article className="b1-workspace-text">
          <span>最后回答</span>
          <p>{compactText(snapshot.last_final_answer ?? '', 180)}</p>
        </article>
      </section>

      <section className="b1-workspace-section">
        <h4>断点</h4>
        <p className="b1-workspace-note">{snapshot.checkpoint}</p>
      </section>
    </div>
  )
}

function workspaceStage(state: WorkspaceLoadState, isRunning: boolean) {
  const workspace = getRecord(state.data?.workspace)
  const task = getRecord(workspace.task)
  const checkpoint = getRecord(state.data?.checkpoint)
  const stage = getString(task, 'stage', getString(checkpoint, 'stage', isRunning ? 'planning' : 'idle'))
  if (stage === 'done' && isRunning) return 'answering'
  return stage
}

function activeNodesForAction(action: B1GraphAction | null) {
  const active = new Set<string>()
  if (!action) return active
  active.add('b1')
  if (action.kind === 'user_to_b1' || action.kind === 'b1_to_user') active.add('user')
  if (action.kind === 'b1_to_b5' || action.kind === 'b5_to_b1') active.add('b5')
  if (action.kind === 'b1_to_b4' || action.kind === 'b4_to_b1') {
    active.add('b4')
    active.add('llm')
  }
  if (action.kind === 'b1_to_tool') {
    active.add('b3')
    active.add('b2')
    active.add('tool')
  }
  if (action.kind === 'tool_to_b1') {
    active.add('tool')
    active.add('b2')
    active.add('b3')
  }
  return active
}

function nodeFlowPhase(action: B1GraphAction | null, nodeId: string) {
  if (!action) return ''
  const paths: Record<B1GraphActionKind, string[]> = {
    user_to_b1: ['user', 'b1'],
    b1_to_b5: ['b1', 'b5'],
    b5_to_b1: ['b5', 'b1'],
    b1_to_b4: ['b1', 'b4', 'llm'],
    b4_to_b1: ['llm', 'b4', 'b1'],
    b1_to_tool: ['b1', 'b3', 'b2', 'tool'],
    tool_to_b1: ['tool', 'b2', 'b3', 'b1'],
    b1_to_user: ['b1', 'user'],
  }
  const path = paths[action.kind]
  const index = path.indexOf(nodeId)
  if (index < 0) return ''
  if (index === 0) return 'flow-origin'
  if (index === path.length - 1) return 'flow-target'
  return `flow-transit flow-transit-${index}`
}

function stageForAction(action: B1GraphAction | null, fallback: string) {
  if (!action) return fallback
  if (action.kind === 'user_to_b1' || action.kind === 'b1_to_b5' || action.kind === 'b5_to_b1') return 'planning'
  if (action.kind === 'b1_to_b4') return 'answering'
  if (action.kind === 'b4_to_b1') return 'observation'
  if (action.kind === 'b1_to_tool') return 'tool_calling'
  if (action.kind === 'tool_to_b1') return 'observation'
  return 'done'
}

function B1TopologyGraph({
  workspaceState,
  isRunning,
  action,
}: {
  workspaceState: WorkspaceLoadState
  isRunning: boolean
  action: B1GraphAction | null
}) {
  const activeStage = workspaceStage(workspaceState, isRunning)
  const toolActive = activeStage === 'tool_calling' || activeStage === 'observation'
  const llmActive = activeStage === 'planning' || activeStage === 'answering'
  const memoryActive = activeStage === 'planning' || activeStage === 'done'
  const actionNodes = activeNodesForAction(action)
  const nodes = [
    { id: 'user', x: 38, y: 132, title: '用户', sub: '输入 / final', external: true },
    { id: 'b1', x: 176, y: 132, title: 'B1', sub: '调度 / workspace', active: actionNodes.has('b1') || isRunning },
    { id: 'b3', x: 330, y: 42, title: 'B3', sub: '解析 / 包装', activeSoft: toolActive },
    { id: 'b2', x: 478, y: 42, title: 'B2', sub: 'skill 执行', activeSoft: toolActive },
    { id: 'tool', x: 620, y: 42, title: 'Tool', sub: '工具能力', external: true },
    { id: 'b4', x: 330, y: 132, title: 'B4', sub: 'LLM 接口', activeSoft: llmActive },
    { id: 'llm', x: 478, y: 132, title: 'LLM源', sub: '模型服务', external: true },
    { id: 'b5', x: 330, y: 222, title: 'B5', sub: 'memory context', activeSoft: memoryActive },
  ]

  return (
    <div className="b1-graph-shell">
      <svg className="b1-topology-svg" viewBox="0 0 720 320" role="img" aria-label="B1 模块拓扑关系">
        <defs>
          <pattern id="b1-grid-pattern" width="24" height="24" patternUnits="userSpaceOnUse">
            <path d="M 24 0 L 0 0 0 24" />
          </pattern>
          <filter id="b1-node-shadow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="4" stdDeviation="4" floodOpacity="0.08" />
          </filter>
        </defs>
        <rect className="b1-svg-bg" x="0" y="0" width="720" height="320" />
        <rect className="b1-svg-grid" x="0" y="0" width="720" height="320" fill="url(#b1-grid-pattern)" />
        <g className="b1-svg-edges">
          <path d="M126 158 L176 158" />
          <path d="M264 146 L330 68" />
          <path d="M264 158 L330 158" />
          <path d="M264 170 L330 248" />
          <path d="M418 68 L478 68" />
          <path d="M566 68 L620 68" />
          <path d="M418 158 L478 158" />
          <path d="M374 184 L374 222" />
        </g>
        <g className="b1-svg-nodes">
          {nodes.map((node) => (
            <g
              className={[
                'b1-svg-node',
                node.external ? 'external' : '',
                node.active ? 'active' : '',
                node.activeSoft || actionNodes.has(node.id) ? 'active-soft' : '',
                nodeFlowPhase(action, node.id),
              ].filter(Boolean).join(' ')}
              key={`${node.id}:${action?.key ?? 'idle'}`}
              transform={`translate(${node.x} ${node.y})`}
            >
              <rect width="88" height="52" rx="9" filter="url(#b1-node-shadow)" />
              <text className="b1-svg-node-title" x="44" y="22">{node.title}</text>
              <text className="b1-svg-node-sub" x="44" y="38">{node.sub}</text>
            </g>
          ))}
        </g>
      </svg>
    </div>
  )
}

function ObservationPanel(props: B1ModuleViewProps & { workspaceState: WorkspaceLoadState }) {
  const { messages, histories, conversationId } = props
  const { track, snapshot } = useB1Observation(props)
  const { workspaceState } = props
  const currentHistory = histories.find((item) => item.id === conversationId)

  return (
    <div className="b1-module">
      <div className="b1-module-head">
        <div>
          <span>B1</span>
          <h2>Agent运行与消息管理模块</h2>
        </div>
      </div>

      <div className="b1-grid">
        <section className="b1-panel b1-track-panel">
          <h3>执行轨道</h3>
          <div className="b1-track" aria-label="B1 模块状态机轨道">
            {track.map((item) => (
              <div className="b1-track-item" key={item.title}>
                <div className={`b1-track-icon ${item.status}`}>
                  <item.Icon size={13} strokeWidth={1.9} aria-hidden="true" />
                </div>
                <div>
                  <header>
                    <span className="b1-module-chip">{item.module}</span>
                    <strong>{item.title}</strong>
                  </header>
                  <div className="b1-track-meta">
                    <span>{item.signal}</span>
                    <code>{item.metric}</code>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="b1-panel b1-flow-panel">
          <h3>消息流</h3>
          <div className="b1-message-flow">
            <article className="b1-message-row memory">
              <span className="b1-role memory">MemoryContext</span>
              <div>
                <header>
                  <strong>B5</strong>
                  <em>{currentHistory?.memoryReady ? 'ready' : 'side channel'}</em>
                </header>
                <p>
                  {currentHistory?.memoryReady
                    ? '当前对话已从 B5 conversation store 读取消息和 tool steps。'
                    : '当前前端旁路尚未拿到 selected/global memory 原文，只能显示 conversation 级状态。'}
                </p>
              </div>
            </article>
            {messages.length === 0 ? (
              <p className="b1-empty">主对话还没有可观察消息。</p>
            ) : (
              messages.map((message, index) => (
                <article className="b1-message-row" key={message.id}>
                  <span className={`b1-role ${message.role}`}>{ROLE_LABELS[message.role]}</span>
                  <div>
                    <header>
                      <strong>#{index + 1}</strong>
                      {message.status && <em>{message.status}</em>}
                      {message.toolDetails && message.toolDetails.length > 0 && <em>{message.toolDetails.length} 项中间过程</em>}
                    </header>
                    <p>{compactText(message.body, 220)}</p>
                    {message.toolDetails && message.toolDetails.length > 0 && (
                      <div className="b1-inline-tool-list">
                        {message.toolDetails.map((detail, detailIndex) => (
                          <section className="b1-inline-tool" key={`${message.id}-${detailIndex}`}>
                            <header>
                              <strong>{detail.label}</strong>
                              {detail.kind && <em>{detail.kind}</em>}
                              {detail.status && <em>{detail.status}</em>}
                            </header>
                            <pre>{detail.body}</pre>
                          </section>
                        ))}
                      </div>
                    )}
                  </div>
                </article>
              ))
            )}
          </div>
        </section>

        <section className="b1-panel b1-workspace-panel">
          <h3>Workspace 快照</h3>
          <WorkspaceSnapshot snapshot={snapshot} messages={messages} workspaceState={workspaceState} />
        </section>
      </div>
    </div>
  )
}

function B1ActionPanel({
  action,
  queuedActions,
}: {
  action: B1GraphAction | null
  queuedActions: B1GraphAction[]
}) {
  return (
    <div className="b1-flow-current-action">
      <header>
        <span>{action?.label ?? 'idle'}</span>
        <em>{queuedActions.length > 0 ? `待播放 ${queuedActions.length}` : '最新'}</em>
      </header>
      <strong>{action ? action.title : '等待新的流转消息'}</strong>
      <p>{action ? action.description : '发送消息后，这里始终显示 B1 最新接收或产生的信息。'}</p>
      {action?.payload !== undefined && <JsonBlock value={action.payload} />}
    </div>
  )
}

function actionDone(actions: B1GraphAction[], kind: B1GraphActionKind) {
  return actions.some((action) => action.kind === kind)
}

function latestTurnKey(conversationId: string | null, runtimeEvents: B1RuntimeEvent[]) {
  const start = runtimeEvents.find((record) => record.event.type === 'start')
  return `${conversationId ?? 'none'}:${start?.id ?? 'empty'}`
}

function WorkspaceBuildPreview({
  currentAction,
  playedActions,
  messages,
  workspaceState,
}: {
  currentAction: B1GraphAction | null
  playedActions: B1GraphAction[]
  messages: ChatMessage[]
  workspaceState: WorkspaceLoadState
}) {
  const visibleActions = currentAction ? [...playedActions, currentAction] : playedActions
  const lastUser = latestMessage(messages, 'user')
  const finalAssistant = latestMessage(messages, 'assistant', false)
  const toolDetails = collectToolDetails(messages)
  const workspace = getRecord(workspaceState.data?.workspace)
  const checkpoint = getRecord(workspaceState.data?.checkpoint)
  const input = getRecord(workspace.input)
  const memory = getRecord(workspace.memory)
  const task = getRecord(workspace.task)
  const tools = getRecord(workspace.tools)
  const draft = getRecord(workspace.draft)
  const final = getRecord(workspace.final)
  const trace = asArray(workspace.trace)
  const runtime = getRecord(workspaceState.data?.runtime)
  const sections = [
    {
      id: 'input',
      title: 'input',
      done: actionDone(visibleActions, 'user_to_b1'),
      current: currentAction?.kind === 'user_to_b1',
      body: compactText(lastUser?.body, 160),
      meta: `${lastUser?.attachments?.length ?? 0} 个上传文件`,
      value: Object.keys(input).length > 0 ? input : {
        conversation_id: workspaceState.data?.conversation_id ?? null,
        user_input: lastUser?.body ?? null,
        attachments: lastUser?.attachments ?? [],
        message_count: messages.length,
      },
    },
    {
      id: 'memory',
      title: 'memory',
      done: actionDone(visibleActions, 'b5_to_b1'),
      current: currentAction?.kind === 'b1_to_b5' || currentAction?.kind === 'b5_to_b1',
      body: workspaceState.data ? '已接收 B5 返回的 conversation / recall context' : '等待 B5 上下文',
      meta: workspaceState.data?.selected_memory ? 'selected memory loaded' : 'side channel pending',
      value: Object.keys(memory).length > 0 ? memory : {
        selected_memory: workspaceState.data?.selected_memory ?? null,
        runtime: workspaceState.data?.runtime ?? null,
      },
    },
    {
      id: 'llm',
      title: 'task / state',
      done: actionDone(visibleActions, 'b1_to_b4') || actionDone(visibleActions, 'b4_to_b1'),
      current: currentAction?.kind === 'b1_to_b4' || currentAction?.kind === 'b4_to_b1',
      body: getString(task, 'stage', workspaceStage(workspaceState, false)),
      meta: `${messages.length} 条 message`,
      value: Object.keys(task).length > 0 ? task : {
        stage: workspaceStage(workspaceState, false),
        action: currentAction?.title ?? null,
        latest_pending: latestMessage(messages, 'assistant')?.status === 'pending',
      },
    },
    {
      id: 'tools',
      title: 'tools',
      done: actionDone(visibleActions, 'b1_to_tool'),
      current: currentAction?.kind === 'b1_to_tool',
      body: toolDetails.length > 0 ? compactText(toolDetails[toolDetails.length - 1].label, 120) : '无工具调用',
      meta: `${toolDetails.length} 项中间过程`,
      value: Object.keys(tools).length > 0 ? tools : {
        details: toolDetails.map((detail) => ({
          label: detail.label,
          kind: detail.kind,
          status: detail.status,
          body: detail.body,
        })),
      },
    },
    {
      id: 'draft',
      title: 'draft',
      done: actionDone(visibleActions, 'b4_to_b1') || actionDone(visibleActions, 'b1_to_tool'),
      current: currentAction?.kind === 'b4_to_b1',
      body: Object.keys(draft).length > 0 ? '已读取运行时草稿字段' : '等待模型阶段判断或工具观察',
      meta: `${trace.length} 条 trace`,
      value: Object.keys(draft).length > 0 ? draft : {
        trace,
        latest_action: currentAction,
      },
    },
    {
      id: 'final',
      title: 'final',
      done: actionDone(visibleActions, 'b1_to_user'),
      current: currentAction?.kind === 'b1_to_user',
      body: compactText(finalAssistant?.body, 160),
      meta: finalAssistant?.artifacts?.length ? `${finalAssistant.artifacts.length} 个生成文件` : 'answer payload',
      value: Object.keys(final).length > 0 ? final : {
        answer: finalAssistant?.body ?? null,
        artifacts: finalAssistant?.artifacts ?? [],
      },
    },
    {
      id: 'trace',
      title: 'trace',
      done: visibleActions.length > 0 && trace.length > 0,
      current: currentAction?.kind === 'b4_to_b1' || currentAction?.kind === 'tool_to_b1',
      body: trace.length > 0 ? `已记录 ${trace.length} 个阶段快照` : '等待阶段轨迹',
      meta: 'workspace trace',
      value: trace,
    },
    {
      id: 'checkpoint',
      title: 'checkpoint',
      done: Boolean(workspaceState.data),
      current: false,
      body: getString(checkpoint, 'status', workspaceState.error ? `读取失败：${workspaceState.error}` : '等待 checkpoint'),
      meta: getString(checkpoint, 'stage', 'stage unknown'),
      value: {
        checkpoint,
        tools_schema_count: workspaceState.data?.tools_schema_count ?? 0,
        status: workspaceState.data?.status ?? null,
      },
    },
    {
      id: 'runtime',
      title: 'runtime / selected memory',
      done: Boolean(workspaceState.data),
      current: false,
      body: workspaceState.data ? '已读取本轮运行参数和记忆选择结果' : '等待运行旁路数据',
      meta: `${workspaceState.data?.tools_schema_count ?? 0} 个 tool schema`,
      value: {
        runtime,
        selected_memory: workspaceState.data?.selected_memory ?? null,
      },
    },
  ]

  return (
    <div className="b1-workspace b1-demo-workspace-build">
      {sections.map((section) => (
        <section
          className={[
            'b1-workspace-section',
            'b1-demo-workspace-step',
            section.done ? 'filled' : '',
            section.current ? 'current' : '',
          ].filter(Boolean).join(' ')}
          key={section.id}
        >
          <h4>{section.title}</h4>
          <p>{section.body}</p>
          <span>{section.meta}</span>
          {(section.done || section.current) && <JsonBlock value={section.value} />}
        </section>
      ))}
    </div>
  )
}

function DemoPanel(props: B1ModuleViewProps & { workspaceState: WorkspaceLoadState }) {
  const { messages, runtimeEvents } = props
  const { workspaceState } = props
  const activeStage = workspaceStage(workspaceState, props.isRunning)
  const stages = ['planning', 'tool_calling', 'observation', 'answering', 'done', 'failed', 'cancelled']
  const detectedActions = useMemo(
    () => buildB1DemoActions({
      runtimeEvents,
      workspaceState,
    }),
    [runtimeEvents, workspaceState],
  )
  const [queuedActions, setQueuedActions] = useState<B1GraphAction[]>([])
  const [playedActions, setPlayedActions] = useState<B1GraphAction[]>([])
  const [currentAction, setCurrentAction] = useState<B1GraphAction | null>(null)
  const seenActionKeys = useRef<Set<string>>(new Set())
  const lastTurn = useRef<string | null>(null)
  const initialized = useRef(false)
  const turnKey = useMemo(
    () => latestTurnKey(props.conversationId, runtimeEvents),
    [props.conversationId, runtimeEvents],
  )

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (!initialized.current) {
        initialized.current = true
        lastTurn.current = turnKey
        seenActionKeys.current = new Set(detectedActions.map((action) => action.key))
        setQueuedActions([])
        setCurrentAction(null)
        setPlayedActions([...detectedActions].reverse().slice(0, 12))
        return
      }
      if (lastTurn.current !== turnKey) {
        lastTurn.current = turnKey
        seenActionKeys.current = new Set(detectedActions.map((action) => action.key))
        setPlayedActions([])
        setCurrentAction(null)
        setQueuedActions(detectedActions)
        return
      }
      const freshActions = detectedActions.filter((action) => !seenActionKeys.current.has(action.key))
      if (freshActions.length === 0) return
      freshActions.forEach((action) => seenActionKeys.current.add(action.key))
      setQueuedActions((items) => [...items, ...freshActions])
    }, 0)
    return () => window.clearTimeout(timer)
  }, [detectedActions, turnKey])

  useEffect(() => {
    if (currentAction || queuedActions.length === 0) return undefined
    const [nextAction, ...rest] = queuedActions
    const timer = window.setTimeout(() => {
      setQueuedActions(rest)
      setCurrentAction(nextAction)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [currentAction, queuedActions])

  useEffect(() => {
    if (!currentAction) return undefined
    const timer = window.setTimeout(() => {
      setPlayedActions((items) => [currentAction, ...items].slice(0, 12))
      setCurrentAction(null)
    }, B1_ACTION_PLAY_MS)
    return () => window.clearTimeout(timer)
  }, [currentAction])
  const displayedStage = stageForAction(currentAction, activeStage)
  const latestAction = detectedActions[detectedActions.length - 1] ?? currentAction ?? playedActions[0] ?? null

  return (
    <div className="b1-module">
      <div className="b1-module-head">
        <div>
          <span>B1</span>
          <h2>信息流与状态控制演示</h2>
        </div>
      </div>

      <div className="b1-demo-control-grid">
        <div className="b1-demo-left-column">
          <section className="b1-panel b1-graph-panel">
            <h3>模块依赖与信息流</h3>
            <B1TopologyGraph workspaceState={workspaceState} isRunning={props.isRunning} action={currentAction} />
          </section>

          <section className="b1-panel b1-state-panel">
            <h3>状态控制</h3>
            <div className="b1-stage-strip">
              {stages.map((stage) => <span className={stage === displayedStage ? 'active' : ''} key={stage}>{stage}</span>)}
            </div>
          </section>

          <section className="b1-panel b1-flow-demo-panel">
            <h3>当前流转信息</h3>
            <B1ActionPanel action={latestAction} queuedActions={queuedActions} />
          </section>
        </div>

        <section className="b1-panel b1-demo-workspace-panel">
          <h3>Workspace 快照</h3>
          <WorkspaceBuildPreview
            currentAction={currentAction}
            playedActions={playedActions}
            messages={messages}
            workspaceState={workspaceState}
          />
        </section>

        <Composer
          attachments={props.attachments}
          dragActive={props.dragActive}
          draft={props.draft}
          canSend={props.canSend}
          inputRef={props.inputRef}
          fileRef={props.fileRef}
          onDraftChange={props.onDraftChange}
          onKeyDown={props.onKeyDown}
          onFileChange={props.onFileChange}
          onRemoveAttachment={props.onRemoveAttachment}
          onSend={props.onSend}
          isRunning={props.isRunning}
          isStopping={props.isStopping}
          onStop={props.onStop}
          promptOpen={props.promptOpen}
          systemPrompt={props.systemPrompt}
          onPromptToggle={props.onPromptToggle}
          onPromptSave={props.onPromptSave}
          onSystemPromptChange={props.onSystemPromptChange}
        />
      </div>
    </div>
  )
}

export function B1ModuleView(props: B1ModuleViewProps) {
  const eventRevision = props.runtimeEvents[props.runtimeEvents.length - 1]?.id ?? 0
  const startEvent = props.runtimeEvents.find((record) => record.event.type === 'start')?.event
  const expectedRunId = startEvent?.type === 'start' ? startEvent.run_id ?? null : null
  const workspaceState = useB1WorkspaceCheckpoint(
    props.conversationId,
    props.isRunning,
    eventRevision,
    expectedRunId,
  )
  return props.mode === 'observe'
    ? <ObservationPanel {...props} workspaceState={workspaceState} />
    : <DemoPanel {...props} workspaceState={workspaceState} />
}
