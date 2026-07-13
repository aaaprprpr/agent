import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEventHandler, ComponentType, KeyboardEventHandler, ReactNode, RefObject } from 'react'
import { Bot, CheckCircle, Circle, Clock, Database, MessageSquare, User, Wrench } from 'lucide-react'

import { API_BASE } from './appConfig'
import { fetchB1WorkspaceSnapshot } from './backendApi'
import { Composer } from './Composer'
import type { Attachment, ChatMessage, HistoryItem } from './types'
import type { B1WorkspaceSnapshot as B1WorkspaceSnapshotPayload } from './types'

type ModuleMode = 'observe' | 'demo'

type B1ModuleViewProps = {
  mode: ModuleMode
  messages: ChatMessage[]
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

type B1GraphActionKind = 'user_to_b1' | 'b1_to_b5' | 'b1_to_b4' | 'b1_to_tool' | 'b1_to_user'

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
  return JSON.stringify(value ?? null, null, 2)
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="b1-json">{jsonText(value)}</pre>
}

function buildB1DemoActions({
  conversationId,
  messages,
  isRunning,
  workspaceState,
}: {
  conversationId: string | null
  messages: ChatMessage[]
  isRunning: boolean
  workspaceState: WorkspaceLoadState
}) {
  const workspace = getRecord(workspaceState.data?.workspace)
  const memory = getRecord(workspace.memory)
  const task = getRecord(workspace.task)
  const tools = collectToolDetails(messages)
  const lastUser = latestMessage(messages, 'user')
  const pendingAssistant = [...messages].reverse().find((message) => message.role === 'assistant' && message.status === 'pending')
  const finalAssistant = latestMessage(messages, 'assistant', false)
  const actions: B1GraphAction[] = []

  if (lastUser) {
    actions.push({
      key: `input:${conversationId ?? 'none'}:${String(lastUser.id)}`,
      kind: 'user_to_b1',
      label: 'input',
      title: '用户输入进入 B1',
      description: compactText(lastUser.body, 260),
      payload: {
        role: 'user',
        message_id: lastUser.id,
        content: lastUser.body,
        attachments: lastUser.attachments ?? [],
      },
    })
  }

  if (workspaceState.data) {
    actions.push({
      key: `memory:${conversationId ?? 'none'}:${String(lastUser?.id ?? messages.length)}:${workspaceState.data.status ?? 'loaded'}`,
      kind: 'b1_to_b5',
      label: 'memory',
      title: 'B1 请求记忆上下文',
      description: 'B5 返回当前会话可用于本轮任务的历史消息、摘要或召回上下文。',
      payload: {
        selected_memory: workspaceState.data?.selected_memory ?? null,
        memory,
      },
    })
  }

  if (pendingAssistant || isRunning || getString(task, 'stage', '') === 'planning' || getString(task, 'stage', '') === 'answering') {
    actions.push({
      key: `llm:${conversationId ?? 'none'}:${String(pendingAssistant?.id ?? lastUser?.id ?? messages.length)}:${getString(task, 'stage', 'running')}`,
      kind: 'b1_to_b4',
      label: 'messages',
      title: 'B1 将消息交给 B4 决策',
      description: pendingAssistant?.body ? compactText(pendingAssistant.body, 260) : 'B1 组装 messages、workspace 阶段输入和系统提示词，交给 B4 调用 LLM 源。',
      payload: {
        stage: getString(task, 'stage', isRunning ? 'running' : 'unknown'),
        pending_assistant_id: pendingAssistant?.id ?? null,
        message_count: messages.length,
        task,
      },
    })
  }

  const lastTool = tools[tools.length - 1]
  if (lastTool) {
    actions.push({
      key: `tool:${conversationId ?? 'none'}:${String(lastTool.messageId)}:${lastTool.detailIndex}:${lastTool.status ?? 'unknown'}`,
      kind: 'b1_to_tool',
      label: lastTool.kind === 'tool' ? 'tool' : 'step',
      title: lastTool.kind === 'tool' ? `B1 调度工具：${lastTool.label}` : `B1 记录中间过程：${lastTool.label}`,
      description: compactText(lastTool.body, 260),
      payload: {
        label: lastTool.label,
        kind: lastTool.kind,
        status: lastTool.status,
        body: lastTool.body,
      },
    })
  }

  if (finalAssistant && finalAssistant.body && finalAssistant.status !== 'pending') {
    actions.push({
      key: `final:${conversationId ?? 'none'}:${String(finalAssistant.id)}:${finalAssistant.body.length}:${finalAssistant.status ?? 'ok'}`,
      kind: 'b1_to_user',
      label: 'final',
      title: 'B1 输出最终回复',
      description: compactText(finalAssistant.body, 260),
      payload: {
        role: 'assistant',
        message_id: finalAssistant.id,
        status: finalAssistant.status ?? 'success',
        content: finalAssistant.body,
        artifacts: finalAssistant.artifacts ?? [],
      },
    })
  }

  return actions
}

function useB1WorkspaceCheckpoint(conversationId: string | null, poll = false) {
  const [state, setState] = useState<WorkspaceLoadState>({ data: null, loading: false, error: null })

  useEffect(() => {
    if (!conversationId) {
      setState({ data: null, loading: false, error: null })
      return
    }
    let active = true
    const load = (showLoading: boolean) => {
      if (showLoading) setState((current) => ({ ...current, loading: !current.data, error: null }))
      fetchB1WorkspaceSnapshot(API_BASE, conversationId)
        .then((data) => {
          if (active) setState({ data, loading: false, error: null })
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
    const timer = poll ? window.setInterval(() => load(false), 1400) : undefined
    return () => {
      active = false
      if (timer) window.clearInterval(timer)
    }
  }, [conversationId, poll])

  return state
}

function statusText(status: TrackStatus) {
  if (status === 'done') return '完成'
  if (status === 'running') return '运行中'
  if (status === 'warning') return '待确认'
  return '等待'
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
  if (action.kind === 'b1_to_b5') active.add('b5')
  if (action.kind === 'b1_to_b4') {
    active.add('b4')
    active.add('llm')
  }
  if (action.kind === 'b1_to_tool') {
    active.add('b3')
    active.add('b2')
    active.add('tool')
  }
  return active
}

function bubbleRoute(action: B1GraphAction) {
  if (action.kind === 'user_to_b1') return '112 147; 152 147; 198 147'
  if (action.kind === 'b1_to_b5') return '270 170; 312 205; 346 247'
  if (action.kind === 'b1_to_b4') return '270 151; 360 166; 500 166'
  if (action.kind === 'b1_to_tool') return '270 113; 350 70; 494 86; 618 86'
  return '182 166; 144 166; 96 166'
}

function GraphBubble({ action }: { action: B1GraphAction }) {
  const width = Math.max(48, Math.min(96, action.label.length * 7 + 22))
  return (
    <g className="b1-svg-bubble" key={action.key}>
      <animateTransform
        attributeName="transform"
        type="translate"
        values={bubbleRoute(action)}
        dur={`${B1_ACTION_PLAY_MS}ms`}
        fill="freeze"
      />
      <rect width={width} height="22" rx="7" />
      <text x={width / 2} y="14">{action.label}</text>
    </g>
  )
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
    { id: 'user', x: 46, y: 132, title: '用户', sub: '输入 / final', external: true },
    { id: 'b1', x: 188, y: 132, title: 'B1', sub: '调度 / workspace', active: actionNodes.has('b1') || isRunning },
    { id: 'b3', x: 336, y: 54, title: 'B3', sub: '解析 / 包装', activeSoft: toolActive },
    { id: 'b2', x: 492, y: 70, title: 'B2', sub: 'skill 执行', activeSoft: toolActive },
    { id: 'tool', x: 626, y: 70, title: 'Tool', sub: '工具能力', external: true },
    { id: 'b4', x: 360, y: 150, title: 'B4', sub: 'LLM 接口', activeSoft: llmActive },
    { id: 'llm', x: 508, y: 150, title: 'LLM源', sub: '模型服务', external: true },
    { id: 'b5', x: 352, y: 232, title: 'B5', sub: 'memory context', activeSoft: memoryActive },
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
          <path d="M126 158 L188 158" />
          <path d="M276 140 L336 90" />
          <path d="M276 158 L360 176" />
          <path d="M276 176 L352 258" />
          <path d="M424 80 L492 96" />
          <path d="M580 96 L626 96" />
          <path d="M448 176 L508 176" />
        </g>
        <g className="b1-svg-nodes">
          {nodes.map((node) => (
            <g
              className={[
                'b1-svg-node',
                node.external ? 'external' : '',
                node.active ? 'active' : '',
                node.activeSoft || actionNodes.has(node.id) ? 'active-soft' : '',
              ].filter(Boolean).join(' ')}
              key={node.id}
              transform={`translate(${node.x} ${node.y})`}
            >
              <rect width="88" height="52" rx="9" filter="url(#b1-node-shadow)" />
              <text className="b1-svg-node-title" x="44" y="22">{node.title}</text>
              <text className="b1-svg-node-sub" x="44" y="38">{node.sub}</text>
            </g>
          ))}
        </g>
        <g className="b1-svg-bubbles">{action ? <GraphBubble action={action} /> : null}</g>
      </svg>
    </div>
  )
}

function ObservationPanel(props: B1ModuleViewProps & { workspaceState: WorkspaceLoadState }) {
  const { messages, histories, conversationId } = props
  const { track, snapshot, runtimeStatus } = useB1Observation(props)
  const { workspaceState } = props
  const currentHistory = histories.find((item) => item.id === conversationId)

  return (
    <div className="b1-module">
      <div className="b1-module-head">
        <div>
          <span>B1</span>
          <h2>Agent运行与消息管理模块</h2>
        </div>
        <strong>{runtimeStatus}</strong>
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
                    <em className={item.status}>
                      {item.status === 'running' ? <Clock size={12} strokeWidth={1.9} aria-hidden="true" /> : null}
                      {item.status === 'done' ? <CheckCircle size={12} strokeWidth={1.9} aria-hidden="true" /> : null}
                      {item.status === 'idle' || item.status === 'warning' ? <Circle size={12} strokeWidth={1.9} aria-hidden="true" /> : null}
                      {statusText(item.status)}
                    </em>
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
  currentAction,
  playedActions,
  queuedActions,
}: {
  currentAction: B1GraphAction | null
  playedActions: B1GraphAction[]
  queuedActions: B1GraphAction[]
}) {
  const log = currentAction ? [currentAction, ...playedActions] : playedActions

  return (
    <>
      <div className="b1-flow-current-action">
        <strong>{currentAction ? currentAction.title : '等待新的流转动作'}</strong>
        <p>{currentAction ? currentAction.description : '对话开始后，B1 旁路会记录真实消息变化，并按顺序驱动关系图动画。'}</p>
        {currentAction?.payload !== undefined && <JsonBlock value={currentAction.payload} />}
      </div>
      <div className="b1-flow-action-log">
        <header>
          <span>动作记录</span>
          <em>{queuedActions.length > 0 ? `队列 ${queuedActions.length}` : '实时'}</em>
        </header>
        {log.length === 0 ? (
          <p className="b1-empty">暂无动作。发送一条消息后，这里会按 B1 视角记录跨模块信息流。</p>
        ) : (
          log.map((action) => (
            <article className={action === currentAction ? 'active' : ''} key={action.key}>
              <span>{action.label}</span>
              <div>
                <strong>{action.title}</strong>
                <p>{action.description}</p>
              </div>
            </article>
          ))
        )}
      </div>
    </>
  )
}

function actionDone(actions: B1GraphAction[], kind: B1GraphActionKind) {
  return actions.some((action) => action.kind === kind)
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
  const task = getRecord(workspace.task)
  const sections = [
    {
      id: 'input',
      title: 'input',
      done: actionDone(visibleActions, 'user_to_b1'),
      current: currentAction?.kind === 'user_to_b1',
      body: compactText(lastUser?.body, 160),
      meta: `${lastUser?.attachments?.length ?? 0} 个上传文件`,
    },
    {
      id: 'memory',
      title: 'memory',
      done: actionDone(visibleActions, 'b1_to_b5'),
      current: currentAction?.kind === 'b1_to_b5',
      body: workspaceState.data ? '已接收 B5 返回的 conversation / recall context' : '等待 B5 上下文',
      meta: workspaceState.data?.selected_memory ? 'selected memory loaded' : 'side channel pending',
    },
    {
      id: 'llm',
      title: 'LLM decision',
      done: actionDone(visibleActions, 'b1_to_b4'),
      current: currentAction?.kind === 'b1_to_b4',
      body: getString(task, 'stage', workspaceStage(workspaceState, false)),
      meta: `${messages.length} 条 message`,
    },
    {
      id: 'tools',
      title: 'tools',
      done: actionDone(visibleActions, 'b1_to_tool'),
      current: currentAction?.kind === 'b1_to_tool',
      body: toolDetails.length > 0 ? compactText(toolDetails[toolDetails.length - 1].label, 120) : '无工具调用',
      meta: `${toolDetails.length} 项中间过程`,
    },
    {
      id: 'final',
      title: 'final',
      done: actionDone(visibleActions, 'b1_to_user'),
      current: currentAction?.kind === 'b1_to_user',
      body: compactText(finalAssistant?.body, 160),
      meta: finalAssistant?.artifacts?.length ? `${finalAssistant.artifacts.length} 个生成文件` : 'answer payload',
    },
    {
      id: 'checkpoint',
      title: 'checkpoint',
      done: Boolean(workspaceState.data),
      current: false,
      body: getString(checkpoint, 'status', workspaceState.error ? `读取失败：${workspaceState.error}` : '等待 checkpoint'),
      meta: getString(checkpoint, 'stage', 'stage unknown'),
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
        </section>
      ))}
    </div>
  )
}

function DemoPanel(props: B1ModuleViewProps & { workspaceState: WorkspaceLoadState }) {
  const { messages } = props
  const { workspaceState } = props
  const activeStage = workspaceStage(workspaceState, props.isRunning)
  const stages = ['planning', 'tool_calling', 'observation', 'answering', 'done', 'failed', 'cancelled']
  const detectedActions = useMemo(
    () => buildB1DemoActions({
      conversationId: props.conversationId,
      messages,
      isRunning: props.isRunning,
      workspaceState,
    }),
    [messages, props.conversationId, props.isRunning, workspaceState],
  )
  const [queuedActions, setQueuedActions] = useState<B1GraphAction[]>([])
  const [playedActions, setPlayedActions] = useState<B1GraphAction[]>([])
  const [currentAction, setCurrentAction] = useState<B1GraphAction | null>(null)
  const seenActionKeys = useRef<Set<string>>(new Set())
  const lastConversation = useRef<string | null>(null)

  useEffect(() => {
    const conversationKey = props.conversationId ?? '__none__'
    const runActive = props.isRunning || messages.some((message) => message.status === 'pending')
    if (lastConversation.current !== conversationKey) {
      lastConversation.current = conversationKey
      seenActionKeys.current = runActive ? new Set() : new Set(detectedActions.map((action) => action.key))
      setQueuedActions([])
      setPlayedActions([])
      setCurrentAction(null)
      if (!runActive) return
    }
    const freshActions = detectedActions.filter((action) => !seenActionKeys.current.has(action.key))
    if (freshActions.length === 0) return
    freshActions.forEach((action) => seenActionKeys.current.add(action.key))
    setQueuedActions((items) => [...items, ...freshActions])
  }, [detectedActions, messages, props.conversationId, props.isRunning])

  useEffect(() => {
    if (currentAction || queuedActions.length === 0) return undefined
    const [nextAction, ...rest] = queuedActions
    setQueuedActions(rest)
    setCurrentAction(nextAction)
    const timer = window.setTimeout(() => {
      setPlayedActions((items) => [nextAction, ...items].slice(0, 12))
      setCurrentAction(null)
    }, B1_ACTION_PLAY_MS)
    return () => window.clearTimeout(timer)
  }, [currentAction, queuedActions])

  return (
    <div className="b1-module">
      <div className="b1-module-head">
        <div>
          <span>B1</span>
          <h2>信息流与状态控制演示</h2>
        </div>
        <strong>前端预览</strong>
      </div>

      <div className="b1-demo-control-grid">
        <section className="b1-panel b1-graph-panel">
          <h3>模块依赖与信息流</h3>
          <B1TopologyGraph workspaceState={workspaceState} isRunning={props.isRunning} action={currentAction} />
        </section>

        <section className="b1-panel b1-state-panel">
          <h3>状态控制</h3>
          <div className="b1-stage-strip">
            {stages.map((stage) => <span className={stage === activeStage ? 'active' : ''} key={stage}>{stage}</span>)}
          </div>
        </section>

        <section className="b1-panel b1-flow-demo-panel">
          <h3>当前流转信息</h3>
          <B1ActionPanel currentAction={currentAction} playedActions={playedActions} queuedActions={queuedActions} />
        </section>

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
  const workspaceState = useB1WorkspaceCheckpoint(props.conversationId, props.isRunning)
  return props.mode === 'observe'
    ? <ObservationPanel {...props} workspaceState={workspaceState} />
    : <DemoPanel {...props} workspaceState={workspaceState} />
}
