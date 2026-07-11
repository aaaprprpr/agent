import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent, KeyboardEvent } from 'react'
import { Trash2 } from 'lucide-react'
import { ChatMessageList } from './ChatMessageList'
import { Composer } from './Composer'
import { arrayBufferToBase64 } from './fileUtils'
import { toolDetailsFromCalls, toolDetailsFromMessages, toolDetailsFromProgress, toolDetailsFromSteps } from './ToolTrace'
import type { Attachment, BackendConversation, BackendMessage, ChatMessage, HistoryItem, RunStreamEvent, UploadedFilePayload } from './types'
import './App.css'

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
          attachments: message.attachments,
        })) satisfies ChatMessage[]
      if (currentConversationIdRef.current !== conversationId) return
      setMessages(loadedMessages)
      updateHistoryMessages(conversationId, loadedMessages, true)
    } finally {
      setIsLoadingHistory(false)
    }
  }

  async function deleteConversation(conversationId: string) {
    if (runningConversationIdsRef.current.has(conversationId)) return
    const item = histories.find((history) => history.id === conversationId)
    const title = item?.title || '当前对话'
    if (!window.confirm(`删除“${title}”？本对话的上传文件也会一并删除。`)) return
    try {
      const response = await fetch(`${API_BASE}/api/conversations/${conversationId}`, { method: 'DELETE' })
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        const detail = payload?.detail ?? `HTTP ${response.status}`
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
      }
      setHistories((current) => current.filter((history) => history.id !== conversationId))
      if (currentConversationIdRef.current === conversationId) {
        stickToBottomRef.current = true
        setActiveConversation(null)
        setMessages([])
        setAttachments([])
        setDraft('')
      }
    } catch (error) {
      window.alert(error instanceof Error ? `删除失败：${error.message}` : '删除失败')
    }
  }

  function addFiles(files: FileList | File[]) {
    const next = Array.from(files).map((file, index) => ({
      id: Date.now() + index,
      name: file.name,
      size: file.size,
      file,
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

  async function buildUploadPayloads(files: Attachment[]): Promise<UploadedFilePayload[]> {
    if (files.length === 0) return []
    return Promise.all(
      files.map(async (item) => ({
        name: item.name,
        size: item.size,
        mime_type: item.file.type || undefined,
        content_base64: arrayBufferToBase64(await item.file.arrayBuffer()),
      })),
    )
  }

  async function handleSend() {
    const text = draft.trim()
    if (!text) return
    stickToBottomRef.current = isConversationAtBottom()
    const conversationId = currentConversationId ?? createConversationId()
    if (runningConversationIdsRef.current.has(conversationId)) return
    const filesToUpload = attachments
    const existingHistory = histories.find((item) => item.id === conversationId)
    const now = Date.now()
    const pendingId = now + 1
    const optimisticMessages: ChatMessage[] = [
      ...messages,
      {
        id: now,
        role: 'user',
        body: text,
        attachments: filesToUpload.map((file) => ({ name: file.name, size: file.size })),
      },
      {
        id: pendingId,
        role: 'assistant',
        body: '...',
        status: 'pending',
      },
    ]
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
                  toolPanelOpen: false,
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
      const uploadPayloads = await buildUploadPayloads(filesToUpload)
      const response = await fetch(`${API_BASE}/api/run/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_input: text,
          conversation_id: conversationId,
          uploaded_file_payloads: uploadPayloads,
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
            <div
              className={`history-item ${item.id === currentConversationId ? 'active' : ''}`}
              key={item.id}
            >
              <button
                className="history-open"
                type="button"
                onClick={() => {
                  setAttachments([])
                  setDraft('')
                  void loadConversation(item.id)
                }}
              >
                <span className="history-copy">
                  <strong>{item.title}</strong>
                </span>
              </button>
              <button
                className="history-delete"
                type="button"
                aria-label={`删除对话 ${item.title}`}
                title="删除对话"
                disabled={runningConversationIds.has(item.id)}
                onClick={() => {
                  void deleteConversation(item.id)
                }}
              >
                <Trash2 size={15} strokeWidth={1.8} aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
      </aside>

      <section className="workspace">
        <ChatMessageList
          messages={messages}
          conversationRef={conversationRef}
          onScroll={updateScrollButton}
          onToggleTool={toggleToolPanel}
        />

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

        <Composer
          attachments={attachments}
          dragActive={dragActive}
          draft={draft}
          canSend={canSend}
          inputRef={inputRef}
          fileRef={fileRef}
          onDraftChange={setDraft}
          onKeyDown={handleKeyDown}
          onFileChange={handleFileChange}
          onRemoveAttachment={(id) => setAttachments((current) => current.filter((item) => item.id !== id))}
          onSend={handleSend}
        />
      </section>
    </main>
  )
}

export default App
