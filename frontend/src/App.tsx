import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent, KeyboardEvent } from 'react'
import './App.css'

type Role = 'user' | 'assistant' | 'tool'

type ChatMessage = {
  id: number | string
  role: Role
  body: string
  status?: 'pending' | 'error'
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
    try {
      const response = await fetch(`${API_BASE}/api/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_input: text,
          conversation_id: conversationId,
        }),
      })
      const payload = await response.json().catch(() => null)
      if (!response.ok) {
        const detail = payload?.detail ?? `HTTP ${response.status}`
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
      }
      const finalMessages: ChatMessage[] = optimisticMessages.map((message): ChatMessage =>
        message.id === pendingId
          ? {
              ...message,
              body: payload?.final_answer || 'Agent 没有返回内容。',
              status: undefined,
            }
          : message,
      )
      const memorySaved = payload?.trace?.memory_save?.status === 'success'
      if (currentConversationIdRef.current === conversationId) {
        stickToBottomRef.current = isConversationAtBottom()
        setMessages(finalMessages)
      }
      updateHistoryMessages(conversationId, finalMessages, memorySaved || existingHistory?.memoryReady)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      const failedMessages: ChatMessage[] = optimisticMessages.map((item): ChatMessage =>
        item.id === pendingId
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
              <div className="message-body">
                {message.status === 'pending' ? <LoadingBubble /> : <p>{message.body}</p>}
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
