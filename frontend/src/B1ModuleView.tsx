import { useMemo, useState } from 'react'
import type { ChangeEvent, ComponentType } from 'react'
import { Bot, CheckCircle, Circle, Clock, Database, MessageSquare, User, Wrench } from 'lucide-react'

import type { ChatMessage, HistoryItem } from './types'

type ModuleMode = 'observe' | 'demo'

type B1ModuleViewProps = {
  mode: ModuleMode
  messages: ChatMessage[]
  histories: HistoryItem[]
  conversationId: string | null
  isRunning: boolean
  isStopping: boolean
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

function WorkspaceSnapshot({ snapshot, messages }: { snapshot: B1Snapshot; messages: ChatMessage[] }) {
  const toolDetails = collectToolDetails(messages)

  return (
    <div className="b1-workspace">
      <section className="b1-workspace-section">
        <h4>会话</h4>
        <dl className="b1-kv">
          <dt>ID</dt>
          <dd>{snapshot.conversation_id ?? '无'}</dd>
          <dt>标题</dt>
          <dd>{snapshot.title ?? '无'}</dd>
          <dt>状态</dt>
          <dd>{snapshot.runtime_status}</dd>
        </dl>
      </section>

      <section className="b1-workspace-section">
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

function ObservationPanel(props: B1ModuleViewProps) {
  const { messages, histories, conversationId } = props
  const { track, snapshot, runtimeStatus } = useB1Observation(props)
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
          <WorkspaceSnapshot snapshot={snapshot} messages={messages} />
        </section>
      </div>
    </div>
  )
}

function DemoPanel() {
  const [userInput, setUserInput] = useState('帮我阅读 docs/agent_intro.txt，总结三条中文要点。')
  const [memoryIds, setMemoryIds] = useState('mem_course_001')
  const [toolset, setToolset] = useState('basic_tools')
  const [loadedName, setLoadedName] = useState('')
  const [loadedJson, setLoadedJson] = useState('')

  const demoPayload = {
    conversation_id: 'demo_b1_manual',
    user_input: userInput,
    selected_memory_ids: memoryIds.split(',').map((item) => item.trim()).filter(Boolean),
    toolset,
    max_turns: 10,
  }

  function loadRuntimeJson(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      const text = String(reader.result ?? '')
      setLoadedName(file.name)
      setLoadedJson(text)
      try {
        const parsed = JSON.parse(text) as Record<string, unknown>
        if (typeof parsed.user_input === 'string') setUserInput(parsed.user_input)
        if (typeof parsed.toolset === 'string') setToolset(parsed.toolset)
        if (Array.isArray(parsed.selected_memory_ids)) setMemoryIds(parsed.selected_memory_ids.join(', '))
      } catch {
        // Keep the raw text visible; invalid JSON should not break the demo page.
      }
    }
    reader.readAsText(file)
    event.target.value = ''
  }

  return (
    <div className="b1-module">
      <div className="b1-module-head">
        <div>
          <span>B1</span>
          <h2>单模块演示输入</h2>
        </div>
        <strong>未执行</strong>
      </div>

      <div className="b1-demo-grid">
        <section className="b1-panel b1-demo-form">
          <h3>构造 B1 输入</h3>
          <label>
            用户输入
            <textarea value={userInput} onChange={(event) => setUserInput(event.target.value)} />
          </label>
          <label>
            selected_memory_ids
            <input value={memoryIds} onChange={(event) => setMemoryIds(event.target.value)} />
          </label>
          <label>
            toolset
            <input value={toolset} onChange={(event) => setToolset(event.target.value)} />
          </label>
          <label className="b1-file-load">
            从 runtime JSON 导入
            <input type="file" accept=".json,application/json" onChange={loadRuntimeJson} />
          </label>
          <button type="button" disabled>
            运行演示
          </button>
          <p>后端 demo API 接入前，这里只负责构造和预览 B1 边界输入。</p>
        </section>

        <section className="b1-panel b1-demo-preview">
          <h3>输入预览</h3>
          {loadedName && <p className="b1-loaded-file">已导入：{loadedName}</p>}
          <pre className="b1-json">{JSON.stringify(demoPayload, null, 2)}</pre>
          {loadedJson && (
            <>
              <h3>原始文件内容</h3>
              <pre className="b1-json">{loadedJson}</pre>
            </>
          )}
        </section>
      </div>
    </div>
  )
}

export function B1ModuleView(props: B1ModuleViewProps) {
  return props.mode === 'observe' ? <ObservationPanel {...props} /> : <DemoPanel />
}
