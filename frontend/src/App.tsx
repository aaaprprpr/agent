import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ChangeEvent, ClipboardEvent, DragEvent, KeyboardEvent } from 'react'
import './App.css'

type Role = 'user' | 'assistant' | 'tool'

type ChatMessage = {
  id: number | string
  role: Role
  body: string
  status?: 'pending' | 'error'
  toolDetails?: ToolDetail[]
  toolPanelOpen?: boolean
}

type ToolDetail = {
  label: string
  body: string
  status?: string
  kind?: 'note' | 'tool'
}

type Attachment = {
  id: number
  name: string
  size: number
}

type HistoryItem = {
  id: string
  title: string
  messages: ChatMessage[]
  memoryReady: boolean
}

type BackendConversation = {
  id: string
  title: string
}

type BackendMessage = {
  id: string
  role: Role
  content: string
  status?: 'pending' | 'error' | null
  tool_steps?: Record<string, unknown>[]
}

type RunStreamEvent =
  | {
      type: 'start'
      conversation_id: string
      user_message_id?: string
      assistant_message_id?: string
    }
  | {
      type: 'delta'
      text: string
      conversation_id?: string
      assistant_message_id?: string
    }
  | {
      type: 'state'
      state: string
      action?: string
      reason?: string
      conversation_id?: string
      assistant_message_id?: string
      llm_call_index?: number
      tool_round_index?: number
      detail?: Record<string, unknown>
    }
  | {
      type: 'tool_start' | 'tool_done'
      conversation_id?: string
      assistant_message_id?: string
      assistant_content?: string
      tool_calls?: unknown[]
      tool_messages?: unknown[]
    }
  | {
      type: 'done'
      conversation_id: string
      user_message_id?: string
      assistant_message_id?: string
      status: string
      final_answer: string
      trace?: {
        final_state?: string
        finish_reason?: string
        memory_save?: { status?: string }
      }
      tool_steps?: Record<string, unknown>[]
    }
  | {
      type: 'error'
      conversation_id?: string
      assistant_message_id?: string
      message: string
    }

const API_BASE = import.meta.env.VITE_AGENT_API_BASE ?? 'http://127.0.0.1:8020'
const ACTIVE_CONVERSATION_KEY = 'agent.activeConversationId'

function pad(value: number, size = 2) {
  return String(value).padStart(size, '0')
}

function createConversationId() {
  const now = new Date()
  return [
    'conv_web',
    `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`,
    `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`,
    pad(now.getMilliseconds(), 3),
  ].join('_')
}

function titleFromInput(text: string) {
  const compact = text.replace(/\s+/g, ' ').trim()
  if (!compact) return '新对话'
  return compact.length > 18 ? `${compact.slice(0, 18)}...` : compact
}

function formatSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function prettyJson(value: unknown) {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function handleMessageCopy(event: ClipboardEvent<HTMLDivElement>) {
  const selectedText = window.getSelection()?.toString()
  if (!selectedText) return
  const normalized = selectedText.replace(/^(?:\r?\n)+|(?:\r?\n)+$/g, '')
  event.clipboardData.setData('text/plain', normalized)
  event.preventDefault()
}

function toolNameFromRecord(value: unknown, fallback: string) {
  if (!value || typeof value !== 'object') return fallback
  const record = value as Record<string, unknown>
  const name = record.name ?? record.tool_name
  return typeof name === 'string' && name.trim() ? name : fallback
}

function progressTextFromStep(step: Record<string, unknown>) {
  const input = step.input
  if (!input || typeof input !== 'object') return ''
  const value = (input as Record<string, unknown>).assistant_content_before_tool
  return typeof value === 'string' ? value.trim() : ''
}

function compactToolStepInput(value: unknown) {
  if (!value || typeof value !== 'object') return value
  const input = value as Record<string, unknown>
  if (input.skill_input !== undefined) return input.skill_input
  const toolCall = input.tool_call
  if (toolCall && typeof toolCall === 'object') {
    const args = (toolCall as Record<string, unknown>).args
    if (args !== undefined) return args
  }
  return value
}

function compactToolStepOutput(value: unknown) {
  if (!value || typeof value !== 'object') return value
  const output = value as Record<string, unknown>
  return output.skill_output !== undefined ? output.skill_output : value
}

function toolDetailsFromProgress(content?: string) {
  const body = content?.trim()
  if (!body) return []
  return [
    {
      label: '工具前说明',
      body,
      status: 'info',
      kind: 'note' as const,
    },
  ]
}

function toolDetailsFromCalls(calls?: unknown[]) {
  if (!Array.isArray(calls) || calls.length === 0) return []
  return calls.map((call, index) => ({
    label: `调用 ${toolNameFromRecord(call, `tool_${index + 1}`)}`,
    body: prettyJson(call),
    status: 'pending',
    kind: 'tool' as const,
  }))
}

function toolDetailsFromSteps(steps?: Record<string, unknown>[]) {
  if (!Array.isArray(steps) || steps.length === 0) return []
  const details: ToolDetail[] = []
  const seenProgress = new Set<string>()
  steps.forEach((step, index) => {
    const progress = progressTextFromStep(step)
    if (progress && !seenProgress.has(progress)) {
      seenProgress.add(progress)
      details.push(...toolDetailsFromProgress(progress))
    }
    details.push({
      label: `${index + 1}. ${toolNameFromRecord(step, 'tool')}`,
      body: prettyJson({
        input: compactToolStepInput(step.input ?? step.input_json),
        output: compactToolStepOutput(step.output ?? step.output_json),
        error: step.error ?? step.error_json,
        latency_ms: step.latency_ms,
      }),
      status: typeof step.status === 'string' ? step.status : undefined,
      kind: 'tool',
    })
  })
  return details
}

function toolDetailsFromMessages(messages?: unknown[]) {
  if (!Array.isArray(messages) || messages.length === 0) return []
  return messages.map((message, index) => ({
    label: `结果 ${toolNameFromRecord(message, `tool_${index + 1}`)}`,
    body: prettyJson(message),
    status:
      message && typeof message === 'object' && typeof (message as Record<string, unknown>).status === 'string'
        ? String((message as Record<string, unknown>).status)
        : undefined,
    kind: 'tool' as const,
  }))
}

function LoadingBubble() {
  return (
    <span className="loading-bubble" aria-label="等待回复">
      <span className="loading-dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
    </span>
  )
}

function ChevronDownIcon() {
  return (
    <svg className="tool-trace-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M4.25 6.25L8 10l3.75-3.75" />
    </svg>
  )
}

function ToolTrace({
  message,
  onToggle,
}: {
  message: ChatMessage
  onToggle: (messageId: number | string) => void
}) {
  const details = message.toolDetails ?? []
  if (details.length === 0) return null
  const open = Boolean(message.toolPanelOpen)
  const active = message.status === 'pending'
  const toolCount = details.filter((detail) => detail.kind !== 'note').length || details.length
  return (
    <div className={`tool-trace ${open ? 'open' : ''}`}>
      <button className="tool-trace-toggle" type="button" onClick={() => onToggle(message.id)}>
        <ChevronDownIcon />
        <span>{active ? '处理中' : '工具调用'}</span>
        <small>{toolCount} 项</small>
      </button>
      {open && (
        <div className="tool-trace-panel">
          {details.map((detail, index) => (
            <section className="tool-trace-item" key={`${detail.label}-${index}`}>
              <div className="tool-trace-title">
                <span>{detail.label}</span>
                {detail.status && <em>{detail.status}</em>}
              </div>
              <pre>{detail.body}</pre>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}

function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [histories, setHistories] = useState<HistoryItem[]>([])
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [draft, setDraft] = useState('')
  const [dragActive, setDragActive] = useState(false)
  const [runningConversationIds, setRunningConversationIds] = useState<Set<string>>(() => new Set())
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const conversationRef = useRef<HTMLElement | null>(null)
  const currentConversationIdRef = useRef<string | null>(null)
  const runningConversationIdsRef = useRef<Set<string>>(new Set())
  const stickToBottomRef = useRef(true)
  const [showScrollBottom, setShowScrollBottom] = useState(false)

  const isCurrentConversationRunning = currentConversationId ? runningConversationIds.has(currentConversationId) : false
  const hasPendingMessage = messages.some((message) => message.status === 'pending')
  const canSend = draft.trim().length > 0 && !isCurrentConversationRunning && !hasPendingMessage

  function setActiveConversation(conversationId: string | null) {
    currentConversationIdRef.current = conversationId
    setCurrentConversationId(conversationId)
    if (conversationId) {
      localStorage.setItem(ACTIVE_CONVERSATION_KEY, conversationId)
    } else {
      localStorage.removeItem(ACTIVE_CONVERSATION_KEY)
    }
  }

  function setConversationRunning(conversationId: string, running: boolean) {
    setRunningConversationIds((current) => {
      const next = new Set(current)
      if (running) {
        next.add(conversationId)
      } else {
        next.delete(conversationId)
      }
      runningConversationIdsRef.current = next
      return next
    })
  }

  function updateHistoryMessages(conversationId: string, nextMessages: ChatMessage[], memoryReady?: boolean) {
    setHistories((current) =>
      current.map((item) =>
        item.id === conversationId
          ? {
              ...item,
              messages: nextMessages,
              memoryReady: memoryReady ?? item.memoryReady,
            }
          : item,
      ),
    )
  }

  function toggleToolPanel(messageId: number | string) {
    const conversationId = currentConversationIdRef.current
    setMessages((current) => {
      const nextMessages = current.map((message) =>
        message.id === messageId ? { ...message, toolPanelOpen: !message.toolPanelOpen } : message,
      )
      if (conversationId) updateHistoryMessages(conversationId, nextMessages)
      return nextMessages
    })
  }

  function isConversationAtBottom() {
    const node = conversationRef.current
    if (!node) return true
    return node.scrollHeight - node.scrollTop - node.clientHeight <= 80
  }

  function updateScrollButton() {
    const node = conversationRef.current
    if (!node) {
      setShowScrollBottom(false)
      return
    }
    const atBottom = isConversationAtBottom()
    const canScroll = node.scrollHeight > node.clientHeight + 4
    stickToBottomRef.current = atBottom
    setShowScrollBottom(canScroll && !atBottom)
  }

  function scrollToBottom(behavior: ScrollBehavior = 'smooth') {
    const node = conversationRef.current
    if (!node) return
    node.scrollTo({ top: node.scrollHeight, behavior })
    stickToBottomRef.current = true
    setShowScrollBottom(false)
  }

  async function loadConversationList() {
    try {
      const response = await fetch(`${API_BASE}/api/conversations`)
      if (!response.ok) return
      const payload = (await response.json()) as BackendConversation[]
      setHistories((current) => {
        const byId = new Map(current.map((item) => [item.id, item]))
        return payload.map((item) => ({
          id: item.id,
          title: item.title,
          messages: byId.get(item.id)?.messages ?? [],
          memoryReady: true,
        }))
      })
      const activeConversationId = localStorage.getItem(ACTIVE_CONVERSATION_KEY)
      if (activeConversationId && payload.some((item) => item.id === activeConversationId)) {
        void loadConversation(activeConversationId)
      }
    } catch {
      // History is optional for the UI; chat can still run without it.
    }
  }

  async function loadConversation(conversationId: string) {
    if (isLoadingHistory) return
    const cached = histories.find((item) => item.id === conversationId)
    stickToBottomRef.current = true
    setActiveConversation(conversationId)
    setMessages(cached?.messages ?? [])
    setAttachments([])
    setDraft('')
    if (runningConversationIdsRef.current.has(conversationId) && cached) return
    setIsLoadingHistory(true)
    try {
      const response = await fetch(`${API_BASE}/api/conversations/${conversationId}`)
      if (!response.ok) return
      const payload = (await response.json()) as { messages: BackendMessage[] }
      const loadedMessages = payload.messages
        .filter((message) => message.role === 'user' || message.role === 'assistant')
        .map((message) => ({
          id: message.id,
          role: message.role,
          body: message.content,
          status: message.status ?? undefined,
          toolDetails: toolDetailsFromSteps(message.tool_steps),
        })) satisfies ChatMessage[]
      if (currentConversationIdRef.current !== conversationId) return
      setMessages(loadedMessages)
      updateHistoryMessages(conversationId, loadedMessages, true)
    } finally {
      setIsLoadingHistory(false)
    }
  }

  function addFiles(files: FileList | File[]) {
    const next = Array.from(files).map((file, index) => ({
      id: Date.now() + index,
      name: file.name,
      size: file.size,
    }))
    setAttachments((current) => [...current, ...next])
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.files) addFiles(event.target.files)
    event.target.value = ''
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragActive(false)
    if (event.dataTransfer.files.length) addFiles(event.dataTransfer.files)
  }

  async function handleSend() {
    const text = draft.trim()
    if (!text) return
    stickToBottomRef.current = isConversationAtBottom()
    const conversationId = currentConversationId ?? createConversationId()
    if (runningConversationIdsRef.current.has(conversationId)) return
    const existingHistory = histories.find((item) => item.id === conversationId)
    const now = Date.now()
    const pendingId = now + 1
    const optimisticMessages = [
      ...messages,
      {
        id: now,
        role: 'user',
        body: text,
      },
      {
        id: pendingId,
        role: 'assistant',
        body: '...',
        status: 'pending',
      },
    ] satisfies ChatMessage[]
    setActiveConversation(conversationId)
    setMessages(optimisticMessages)
    setHistories((current) => {
      const exists = current.some((item) => item.id === conversationId)
      if (exists) {
        return current.map((item) => (item.id === conversationId ? { ...item, messages: optimisticMessages } : item))
      }
      return [
        {
          id: conversationId,
          title: titleFromInput(text),
          messages: optimisticMessages,
          memoryReady: false,
        },
        ...current,
      ]
    })
    setDraft('')
    setAttachments([])
    setConversationRunning(conversationId, true)
    requestAnimationFrame(() => {
      if (inputRef.current) inputRef.current.style.height = '24px'
    })
    let activeUserId: number | string = now
    let activeAssistantId: number | string = pendingId
    let streamedAnswer = ''
    let currentMessages = optimisticMessages

    function applyMessageState(nextMessages: ChatMessage[], memoryReady?: boolean) {
      currentMessages = nextMessages
      if (currentConversationIdRef.current === conversationId) {
        stickToBottomRef.current = isConversationAtBottom()
        setMessages(nextMessages)
      }
      updateHistoryMessages(conversationId, nextMessages, memoryReady)
    }

    function replaceAssistant(body: string, status?: 'pending' | 'error', memoryReady?: boolean) {
      applyMessageState(
        currentMessages.map((message): ChatMessage =>
          message.id === activeAssistantId
            ? {
                ...message,
                body,
                status,
              }
            : message,
        ),
        memoryReady,
      )
    }

    function adoptBackendMessageIds(event: Extract<RunStreamEvent, { type: 'start' }>) {
      const nextUserId = event.user_message_id ?? activeUserId
      const nextAssistantId = event.assistant_message_id ?? activeAssistantId
      applyMessageState(
        currentMessages.map((message): ChatMessage => {
          if (message.id === activeUserId) return { ...message, id: nextUserId }
          if (message.id === activeAssistantId) return { ...message, id: nextAssistantId }
          return message
        }),
      )
      activeUserId = nextUserId
      activeAssistantId = nextAssistantId
    }

    function handleStreamEvent(event: RunStreamEvent) {
      if (event.type === 'start') {
        adoptBackendMessageIds(event)
        return
      }
      if (event.type === 'delta') {
        streamedAnswer += event.text
        replaceAssistant(streamedAnswer, 'pending')
        return
      }
      if (event.type === 'state') return
      if (event.type === 'tool_start') {
        streamedAnswer = ''
        const toolDetails = [
          ...toolDetailsFromProgress(event.assistant_content),
          ...toolDetailsFromCalls(event.tool_calls),
        ]
        if (toolDetails.length === 0) return
        applyMessageState(
          currentMessages.map((message): ChatMessage =>
            message.id === activeAssistantId
              ? {
                  ...message,
                  body: '...',
                  toolDetails: [...(message.toolDetails ?? []), ...toolDetails],
                  toolPanelOpen: true,
                }
              : message,
          ),
        )
        return
      }
      if (event.type === 'tool_done') {
        const resultDetails = toolDetailsFromMessages(event.tool_messages)
        applyMessageState(
          currentMessages.map((message): ChatMessage =>
            message.id === activeAssistantId
              ? {
                  ...message,
                  toolDetails: [
                    ...(message.toolDetails ?? []).map((detail) =>
                      detail.status === 'pending' ? { ...detail, status: 'done' } : detail,
                    ),
                    ...resultDetails,
                  ],
                }
              : message,
          ),
        )
        return
      }
      if (event.type === 'done') {
        const finalAnswer = event.final_answer || streamedAnswer || 'Agent 没有返回内容。'
        const memorySaved = event.trace?.memory_save?.status === 'success'
        const savedToolDetails = toolDetailsFromSteps(event.tool_steps)
        applyMessageState(
          currentMessages.map((message): ChatMessage =>
            message.id === activeAssistantId
              ? {
                  ...message,
                  body: finalAnswer,
                  status: undefined,
                  toolDetails: savedToolDetails.length > 0 ? savedToolDetails : message.toolDetails,
                }
              : message,
          ),
          memorySaved || existingHistory?.memoryReady,
        )
        return
      }
      if (event.type === 'error') {
        throw new Error(event.message)
      }
    }

    function consumeStreamLine(line: string) {
      const trimmed = line.trim()
      if (!trimmed) return
      handleStreamEvent(JSON.parse(trimmed) as RunStreamEvent)
    }

    try {
      const response = await fetch(`${API_BASE}/api/run/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_input: text,
          conversation_id: conversationId,
        }),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        const detail = payload?.detail ?? `HTTP ${response.status}`
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
      }
      if (!response.body) {
        throw new Error('浏览器没有返回可读的流式响应')
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) consumeStreamLine(line)
      }
      buffer += decoder.decode()
      consumeStreamLine(buffer)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      const failedMessages: ChatMessage[] = currentMessages.map((item): ChatMessage =>
        item.id === activeAssistantId
          ? {
              ...item,
              body: `请求失败：${message}`,
              status: 'error',
            }
          : item,
      )
      if (currentConversationIdRef.current === conversationId) {
        stickToBottomRef.current = isConversationAtBottom()
        setMessages(failedMessages)
      }
      updateHistoryMessages(conversationId, failedMessages)
    } finally {
      setConversationRunning(conversationId, false)
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      handleSend()
    }
  }

  function resizeInput() {
    const node = inputRef.current
    if (!node) return
    node.style.height = '24px'
    node.style.height = `${Math.min(node.scrollHeight, 180)}px`
  }

  useLayoutEffect(() => {
    resizeInput()
  }, [draft])

  useEffect(() => {
    loadConversationList()
  }, [])

  useEffect(() => {
    if (!currentConversationId || !hasPendingMessage || runningConversationIds.has(currentConversationId)) return
    const timer = window.setInterval(() => {
      void loadConversation(currentConversationId)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [currentConversationId, hasPendingMessage, runningConversationIds])

  useLayoutEffect(() => {
    if (stickToBottomRef.current) {
      scrollToBottom('auto')
      return
    }
    updateScrollButton()
  }, [messages])

  return (
    <main
      className={`app-shell ${dragActive ? 'is-dragging' : ''}`}
      onDragOver={(event) => {
        event.preventDefault()
        setDragActive(true)
      }}
      onDragLeave={(event) => {
        if (event.currentTarget === event.target) setDragActive(false)
      }}
      onDrop={handleDrop}
    >
      <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
        <div className="sidebar-top">
          <button
            className="icon-button"
            type="button"
            aria-label="折叠侧栏"
            onClick={() => setSidebarCollapsed((value) => !value)}
          >
            <span aria-hidden="true">☰</span>
          </button>
          <div className="brand">
            <strong>Agent</strong>
          </div>
        </div>

        <button
          className="new-chat"
          type="button"
          onClick={() => {
            stickToBottomRef.current = true
            setMessages([])
            setActiveConversation(null)
            setAttachments([])
            setDraft('')
          }}
        >
          <span aria-hidden="true">＋</span>
          <span>新对话</span>
        </button>

        <div className="history-list" aria-label="对话记录">
          {histories.map((item) => (
            <button
              className={`history-item ${item.id === currentConversationId ? 'active' : ''}`}
              key={item.id}
              type="button"
              onClick={() => {
                void loadConversation(item.id)
              }}
            >
              <span className="history-copy">
                <strong>{item.title}</strong>
              </span>
            </button>
          ))}
        </div>
      </aside>

      <section className="workspace">
        <section className="conversation" aria-label="消息列表" ref={conversationRef} onScroll={updateScrollButton}>
          {messages.map((message) => (
            <article className={`message ${message.role} ${message.status ?? ''}`} key={message.id}>
              <div className="message-body" onCopy={handleMessageCopy}>
                {message.role === 'assistant' && <ToolTrace message={message} onToggle={toggleToolPanel} />}
                {message.status === 'pending' && (!message.body || message.body === '...') ? (
                  <LoadingBubble />
                ) : (
                  <p>{message.body}</p>
                )}
              </div>
            </article>
          ))}
        </section>

        {showScrollBottom && (
          <button
            className="scroll-bottom-button"
            type="button"
            aria-label="跳到最新消息"
            onClick={() => scrollToBottom()}
          >
            ↓
          </button>
        )}

        <section className="composer-wrap">
          {dragActive && <div className="drop-hint">释放文件</div>}

          <div className="composer">
            {attachments.length > 0 && (
              <div className="attachment-row">
                {attachments.map((file) => (
                  <div className="attachment-chip" key={file.id}>
                    <span className="file-icon" aria-hidden="true">▣</span>
                    <span>
                      <strong>{file.name}</strong>
                      <small>{formatSize(file.size)}</small>
                    </span>
                    <button
                      type="button"
                      aria-label={`移除 ${file.name}`}
                      onClick={() => setAttachments((current) => current.filter((item) => item.id !== file.id))}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="composer-main">
              <button className="tool-button" type="button" aria-label="添加文件" onClick={() => fileRef.current?.click()}>
                <span aria-hidden="true">＋</span>
              </button>
              <textarea
                ref={inputRef}
                value={draft}
                rows={1}
                autoComplete="off"
                spellCheck={false}
                placeholder="输入任务..."
                onChange={(event) => {
                  setDraft(event.target.value)
                }}
                onKeyDown={handleKeyDown}
              />
              <button className="send-button" type="button" disabled={!canSend} aria-label="发送" onClick={handleSend}>
                <span aria-hidden="true">↑</span>
              </button>
              <input ref={fileRef} type="file" multiple hidden onChange={handleFileChange} />
            </div>
          </div>
        </section>
      </section>
    </main>
  )
}

export default App
