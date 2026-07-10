import { useLayoutEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent, KeyboardEvent } from 'react'
import './App.css'

type Role = 'user' | 'assistant' | 'tool'

type ChatMessage = {
  id: number
  role: Role
  body: string
  status?: 'pending' | 'error'
}

type Attachment = {
  id: number
  name: string
  size: number
}

const histories = [
  { title: '完整演示 / conv_001' },
  { title: '表格分析任务' },
  { title: '工具检索测试' },
  { title: '格式转换样例' },
]

const seedMessages: ChatMessage[] = []

const API_BASE = import.meta.env.VITE_AGENT_API_BASE ?? 'http://127.0.0.1:8020'

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
  const [messages, setMessages] = useState<ChatMessage[]>(seedMessages)
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [draft, setDraft] = useState('')
  const [dragActive, setDragActive] = useState(false)
  const [isRunning, setIsRunning] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)

  const canSend = draft.trim().length > 0 && !isRunning

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
    if (!text || isRunning) return
    const now = Date.now()
    const pendingId = now + 1
    setMessages((current) => [
      ...current,
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
    ])
    setDraft('')
    setAttachments([])
    setIsRunning(true)
    requestAnimationFrame(() => {
      if (inputRef.current) inputRef.current.style.height = '24px'
    })
    try {
      const response = await fetch(`${API_BASE}/api/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_input: text }),
      })
      const payload = await response.json().catch(() => null)
      if (!response.ok) {
        const detail = payload?.detail ?? `HTTP ${response.status}`
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
      }
      setMessages((current) =>
        current.map((message) =>
          message.id === pendingId
            ? {
                ...message,
                body: payload?.final_answer || 'Agent 没有返回内容。',
                status: undefined,
              }
            : message,
        ),
      )
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setMessages((current) =>
        current.map((item) =>
          item.id === pendingId
            ? {
                ...item,
                body: `请求失败：${message}`,
                status: 'error',
              }
            : item,
        ),
      )
    } finally {
      setIsRunning(false)
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
            setMessages(seedMessages)
            setAttachments([])
            setDraft('')
          }}
        >
          <span aria-hidden="true">＋</span>
          <span>新建任务</span>
        </button>

        <div className="history-list" aria-label="对话记录">
          {histories.map((item, index) => (
            <button className={`history-item ${index === 0 ? 'active' : ''}`} key={item.title} type="button">
              <span className="history-copy">
                <strong>{item.title}</strong>
              </span>
            </button>
          ))}
        </div>
      </aside>

      <section className="workspace">
        <section className="conversation" aria-label="消息列表">
          {messages.map((message) => (
            <article className={`message ${message.role} ${message.status ?? ''}`} key={message.id}>
              <div className="message-body">
                {message.status === 'pending' ? <LoadingBubble /> : <p>{message.body}</p>}
              </div>
            </article>
          ))}
        </section>

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
