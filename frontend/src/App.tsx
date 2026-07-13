import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent, KeyboardEvent } from 'react'
import { Trash2 } from 'lucide-react'
import { API_BASE, ACTIVE_CONVERSATION_KEY } from './appConfig'
import {
  deleteBackendConversation,
  fetchConversationList,
  fetchConversationMessages,
  requestConversationCancel,
  startResumeStream,
  startRunStream,
} from './backendApi'
import { ChatMessageList } from './ChatMessageList'
import { Composer } from './Composer'
import { createConversationId, titleFromInput } from './conversationUtils'
import { backendMessagesToChatMessages } from './messageAdapters'
import {
  artifactsFromToolMessages,
  artifactsFromToolSteps,
  mergeArtifacts,
  toolDetailsFromAgentStep,
  toolDetailsFromCalls,
  toolDetailsFromMessages,
  toolDetailsFromProgress,
  toolDetailsFromSteps,
} from './toolTraceUtils'
import { buildUploadPayloads } from './uploadUtils'
import type { Attachment, ChatMessage, HistoryItem, RunStreamEvent } from './types'
import { B1ModuleView } from './B1ModuleView'
import './App.css'

const MODULE_VIEWS = [
  { id: 'b1', label: 'B1', title: 'Agent运行与消息管理模块' },
  { id: 'b2', label: 'B2', title: 'Skill工具函数模块' },
  { id: 'b3', label: 'B3', title: '说明生成与工具调用模块' },
  { id: 'b4', label: 'B4', title: 'Agent LLM决策模块' },
  { id: 'b5', label: 'B5', title: '记忆文档存储与查找模块' },
] as const

type ModuleViewId = (typeof MODULE_VIEWS)[number]['id']
type ActiveViewId = 'chat' | ModuleViewId
type ModuleMode = 'observe' | 'demo'

const DEFAULT_MODULE_MODES: Record<ModuleViewId, ModuleMode> = {
  b1: 'observe',
  b2: 'observe',
  b3: 'observe',
  b4: 'observe',
  b5: 'observe',
}

function App() {
  const [activeView, setActiveView] = useState<ActiveViewId>('chat')
  const [moduleModes, setModuleModes] = useState<Record<ModuleViewId, ModuleMode>>(DEFAULT_MODULE_MODES)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [histories, setHistories] = useState<HistoryItem[]>([])
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [draft, setDraft] = useState('')
  const [dragActive, setDragActive] = useState(false)
  const [runningConversationIds, setRunningConversationIds] = useState<Set<string>>(() => new Set())
  const [cancellingConversationIds, setCancellingConversationIds] = useState<Set<string>>(() => new Set())
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const conversationRef = useRef<HTMLElement | null>(null)
  const currentConversationIdRef = useRef<string | null>(null)
  const runningConversationIdsRef = useRef<Set<string>>(new Set())
  const cancellingConversationIdsRef = useRef<Set<string>>(new Set())
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map())
  const stickToBottomRef = useRef(true)
  const [showScrollBottom, setShowScrollBottom] = useState(false)

  const isCurrentConversationRunning = currentConversationId ? runningConversationIds.has(currentConversationId) : false
  const isCurrentConversationStopping = currentConversationId ? cancellingConversationIds.has(currentConversationId) : false
  const hasPendingMessage = messages.some((message) => message.status === 'pending')
  const canSend = draft.trim().length > 0 && !isCurrentConversationRunning && !isCurrentConversationStopping && !hasPendingMessage
  const isChatView = activeView === 'chat'
  const activeModule = isChatView ? null : MODULE_VIEWS.find((item) => item.id === activeView) ?? null
  const activeModuleMode = activeModule ? moduleModes[activeModule.id] : 'observe'

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

  function setConversationCancelling(conversationId: string, cancelling: boolean) {
    setCancellingConversationIds((current) => {
      const next = new Set(current)
      if (cancelling) {
        next.add(conversationId)
      } else {
        next.delete(conversationId)
      }
      cancellingConversationIdsRef.current = next
      return next
    })
  }

  function stopConversation(conversationId: string | null = currentConversationIdRef.current) {
    if (!conversationId || !runningConversationIdsRef.current.has(conversationId)) return
    if (cancellingConversationIdsRef.current.has(conversationId)) return
    setConversationCancelling(conversationId, true)
    const markStopped = (items: ChatMessage[]) =>
      items.map((message): ChatMessage =>
        message.role === 'assistant' && message.status === 'pending'
          ? {
              ...message,
              body: message.body && message.body !== '...' ? `${message.body.trimEnd()}\n\n（回答已终止）` : '已终止回答。',
              status: 'cancelled',
              resumable: true,
              toolPanelOpen: false,
              toolDetails: message.toolDetails?.map((detail) =>
                detail.status === 'pending' ? { ...detail, status: 'done' } : detail,
              ),
            }
          : message,
      )
    setMessages((current) => {
      const next = markStopped(current)
      updateHistoryMessages(conversationId, next)
      return next
    })
    abortControllersRef.current.get(conversationId)?.abort()
    void requestConversationCancel(API_BASE, conversationId).catch(() => undefined)
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
      const payload = await fetchConversationList(API_BASE)
      if (!payload) return
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
      const payload = await fetchConversationMessages(API_BASE, conversationId)
      if (!payload) return
      const loadedMessages = backendMessagesToChatMessages(payload.messages)
      if (currentConversationIdRef.current !== conversationId) return
      setMessages(loadedMessages)
      updateHistoryMessages(conversationId, loadedMessages, true)
    } finally {
      setIsLoadingHistory(false)
    }
  }

  async function deleteConversation(conversationId: string) {
    if (runningConversationIdsRef.current.has(conversationId)) return
    try {
      await deleteBackendConversation(API_BASE, conversationId)
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

  function handleDrop(event: DragEvent<HTMLElement>) {
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
    setConversationCancelling(conversationId, false)
    const abortController = new AbortController()
    abortControllersRef.current.set(conversationId, abortController)
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

    function replaceAssistant(body: string, status?: ChatMessage['status'], memoryReady?: boolean) {
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
      if (event.type === 'state') {
        const toolDetails = toolDetailsFromAgentStep(event.agent_step)
        if (toolDetails.length > 0) {
          applyMessageState(
            currentMessages.map((message): ChatMessage =>
              message.id === activeAssistantId
                ? {
                    ...message,
                    body: message.body || '...',
                    status: 'pending',
                    toolDetails: [...(message.toolDetails ?? []), ...toolDetails],
                    toolPanelOpen: true,
                  }
                : message,
            ),
          )
        }
        return
      }
      if (event.type === 'tool_start') {
        streamedAnswer = ''
        const toolDetails = [
          ...toolDetailsFromAgentStep(event.agent_step),
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
        const resultArtifacts = artifactsFromToolMessages(event.tool_messages)
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
                  artifacts: mergeArtifacts(message.artifacts, resultArtifacts),
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
        const savedArtifacts = artifactsFromToolSteps(event.tool_steps)
        applyMessageState(
          currentMessages.map((message): ChatMessage =>
            message.id === activeAssistantId
              ? {
                  ...message,
                  body: finalAnswer,
                  status: event.status === 'cancelled' ? 'cancelled' : undefined,
                  resumable: event.status === 'cancelled' ? Boolean(event.trace?.checkpoint?.exists) : false,
                  toolDetails: savedToolDetails.length > 0 ? savedToolDetails : message.toolDetails,
                  toolPanelOpen: false,
                  artifacts: mergeArtifacts(message.artifacts, savedArtifacts),
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
      const response = await startRunStream(
        API_BASE,
        {
          user_input: text,
          conversation_id: conversationId,
          uploaded_file_payloads: uploadPayloads,
        },
        abortController.signal,
      )
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
      const aborted = error instanceof DOMException
        ? error.name === 'AbortError'
        : error instanceof Error && error.name === 'AbortError'
      const message = error instanceof Error ? error.message : String(error)
      const failedMessages: ChatMessage[] = currentMessages.map((item): ChatMessage =>
        item.id === activeAssistantId
          ? {
              ...item,
              body: aborted
                ? streamedAnswer.trim()
                  ? `${streamedAnswer.trimEnd()}\n\n（回答已终止）`
                  : '已终止回答。'
                : `请求失败：${message}`,
              status: aborted ? 'cancelled' : 'error',
              resumable: aborted ? true : item.resumable,
              toolPanelOpen: aborted ? false : item.toolPanelOpen,
              toolDetails: aborted
                ? item.toolDetails?.map((detail) =>
                    detail.status === 'pending' ? { ...detail, status: 'done' } : detail,
                  )
                : item.toolDetails,
            }
          : item,
      )
      if (currentConversationIdRef.current === conversationId) {
        stickToBottomRef.current = isConversationAtBottom()
        setMessages(failedMessages)
      }
      updateHistoryMessages(conversationId, failedMessages)
    } finally {
      abortControllersRef.current.delete(conversationId)
      setConversationCancelling(conversationId, false)
      setConversationRunning(conversationId, false)
    }
  }

  async function handleResumeMessage(assistantMessageId: number | string) {
    const conversationId = currentConversationIdRef.current
    if (!conversationId || runningConversationIdsRef.current.has(conversationId)) return
    const resumeConversationId = conversationId
    stickToBottomRef.current = isConversationAtBottom()
    setConversationRunning(resumeConversationId, true)
    setConversationCancelling(resumeConversationId, false)
    const abortController = new AbortController()
    abortControllersRef.current.set(resumeConversationId, abortController)
    let streamedAnswer = ''
    let currentMessages = messages.map((message): ChatMessage =>
      message.id === assistantMessageId
        ? {
            ...message,
            body: '...',
            status: 'pending',
          }
        : message,
    )

    function applyMessageState(nextMessages: ChatMessage[], memoryReady?: boolean) {
      currentMessages = nextMessages
      if (currentConversationIdRef.current === resumeConversationId) {
        stickToBottomRef.current = isConversationAtBottom()
        setMessages(nextMessages)
      }
      updateHistoryMessages(resumeConversationId, nextMessages, memoryReady)
    }

    function replaceAssistant(body: string, status?: ChatMessage['status'], memoryReady?: boolean) {
      applyMessageState(
        currentMessages.map((message): ChatMessage =>
          message.id === assistantMessageId
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

    applyMessageState(currentMessages)

    function handleStreamEvent(event: RunStreamEvent) {
      if (event.type === 'start') return
      if (event.type === 'delta') {
        streamedAnswer += event.text
        replaceAssistant(streamedAnswer, 'pending')
        return
      }
      if (event.type === 'state') {
        const toolDetails = toolDetailsFromAgentStep(event.agent_step)
        if (toolDetails.length > 0) {
          applyMessageState(
            currentMessages.map((message): ChatMessage =>
              message.id === assistantMessageId
                ? {
                    ...message,
                    body: message.body || '...',
                    status: 'pending',
                    toolDetails: [...(message.toolDetails ?? []), ...toolDetails],
                    toolPanelOpen: true,
                  }
                : message,
            ),
          )
        }
        return
      }
      if (event.type === 'tool_start') {
        streamedAnswer = ''
        const toolDetails = [
          ...toolDetailsFromAgentStep(event.agent_step),
          ...toolDetailsFromProgress(event.assistant_content),
          ...toolDetailsFromCalls(event.tool_calls),
        ]
        applyMessageState(
          currentMessages.map((message): ChatMessage =>
            message.id === assistantMessageId
              ? {
                  ...message,
                  body: '...',
                  status: 'pending',
                  toolDetails: toolDetails.length > 0 ? [...(message.toolDetails ?? []), ...toolDetails] : message.toolDetails,
                  toolPanelOpen: true,
                }
              : message,
          ),
        )
        return
      }
      if (event.type === 'tool_done') {
        const resultDetails = toolDetailsFromMessages(event.tool_messages)
        const resultArtifacts = artifactsFromToolMessages(event.tool_messages)
        applyMessageState(
          currentMessages.map((message): ChatMessage =>
            message.id === assistantMessageId
              ? {
                  ...message,
                  toolDetails: [
                    ...(message.toolDetails ?? []).map((detail) =>
                      detail.status === 'pending' ? { ...detail, status: 'done' } : detail,
                    ),
                    ...resultDetails,
                  ],
                  artifacts: mergeArtifacts(message.artifacts, resultArtifacts),
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
        const savedArtifacts = artifactsFromToolSteps(event.tool_steps)
        applyMessageState(
          currentMessages.map((message): ChatMessage =>
            message.id === assistantMessageId
              ? {
                  ...message,
                  body: finalAnswer,
                  status: event.status === 'cancelled' ? 'cancelled' : undefined,
                  resumable: event.status === 'cancelled' ? Boolean(event.trace?.checkpoint?.exists) : false,
                  toolDetails: savedToolDetails.length > 0 ? savedToolDetails : message.toolDetails,
                  toolPanelOpen: false,
                  artifacts: mergeArtifacts(message.artifacts, savedArtifacts),
                }
              : message,
          ),
          memorySaved,
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
      const response = await startResumeStream(API_BASE, resumeConversationId, assistantMessageId, abortController.signal)
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
      const aborted = error instanceof DOMException
        ? error.name === 'AbortError'
        : error instanceof Error && error.name === 'AbortError'
      const message = error instanceof Error ? error.message : String(error)
      applyMessageState(
        currentMessages.map((item): ChatMessage =>
          item.id === assistantMessageId
            ? {
                ...item,
                body: aborted
                  ? streamedAnswer.trim()
                    ? `${streamedAnswer.trimEnd()}\n\n（回答已终止）`
                    : '已终止回答。'
                  : `恢复失败：${message}`,
                status: aborted ? 'cancelled' : 'error',
                toolPanelOpen: aborted ? false : item.toolPanelOpen,
                toolDetails: aborted
                  ? item.toolDetails?.map((detail) =>
                      detail.status === 'pending' ? { ...detail, status: 'done' } : detail,
                    )
                  : item.toolDetails,
              }
            : item,
        ),
      )
    } finally {
      abortControllersRef.current.delete(resumeConversationId)
      setConversationCancelling(resumeConversationId, false)
      setConversationRunning(resumeConversationId, false)
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      handleSend()
    }
  }

  function toggleModuleMode(moduleId: ModuleViewId) {
    setModuleModes((current) => ({
      ...current,
      [moduleId]: current[moduleId] === 'observe' ? 'demo' : 'observe',
    }))
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
    const timer = window.setTimeout(() => {
      void loadConversationList()
    }, 0)
    return () => window.clearTimeout(timer)
    // Initial history hydration should run once after mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!currentConversationId || !hasPendingMessage || runningConversationIds.has(currentConversationId)) return
    const timer = window.setInterval(() => {
      void loadConversation(currentConversationId)
    }, 2000)
    return () => window.clearInterval(timer)
    // Polling intentionally follows the selected conversation id and pending/running flags.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentConversationId, hasPendingMessage, runningConversationIds])

  useLayoutEffect(() => {
    if (stickToBottomRef.current) {
      scrollToBottom('auto')
      return
    }
    updateScrollButton()
    // Scroll adjustment is tied to message updates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages])

  return (
    <main
      className={`app-shell ${isChatView && dragActive ? 'is-dragging' : ''}`}
      onDragOver={(event) => {
        if (!isChatView) return
        event.preventDefault()
        setDragActive(true)
      }}
      onDragLeave={(event) => {
        if (!isChatView) return
        if (event.currentTarget === event.target) setDragActive(false)
      }}
      onDrop={(event) => {
        if (!isChatView) return
        handleDrop(event)
      }}
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

        <div className="module-tabs" aria-label="验收模块">
          {MODULE_VIEWS.map((item) => (
            <button
              className={`module-tab ${item.id === activeView ? 'active' : ''}`}
              type="button"
              key={item.id}
              title={`${item.label} ${item.title}`}
              onClick={() => {
                setActiveView(item.id)
                setDragActive(false)
              }}
            >
              <span>{item.label}</span>
              <small>{item.title}</small>
            </button>
          ))}
        </div>

        <button
          className="new-chat"
          type="button"
          onClick={() => {
            setActiveView('chat')
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
                  setActiveView('chat')
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
                disabled={runningConversationIds.has(item.id) || cancellingConversationIds.has(item.id)}
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
        {isChatView ? (
          <>
            <ChatMessageList
              messages={messages}
              apiBase={API_BASE}
              conversationRef={conversationRef}
              onScroll={updateScrollButton}
              onToggleTool={toggleToolPanel}
              onResumeMessage={handleResumeMessage}
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
              isRunning={isCurrentConversationRunning}
              isStopping={isCurrentConversationStopping}
              onStop={() => stopConversation(currentConversationId)}
            />
          </>
        ) : (
          <section className="module-placeholder" aria-label={`${activeView.toUpperCase()} 验收界面`}>
            {activeModule && (
              <button
                className={`module-mode-switch ${activeModuleMode === 'demo' ? 'is-demo' : ''}`}
                type="button"
                aria-label={`切换${activeModule.label}展示模式`}
                aria-pressed={activeModuleMode === 'demo'}
                onClick={() => toggleModuleMode(activeModule.id)}
              >
                <span className="mode-label">观察</span>
                <span className="mode-label">演示</span>
                <span className="mode-thumb" aria-hidden="true" />
              </button>
            )}
            {activeModule?.id === 'b1' && (
              <B1ModuleView
                mode={activeModuleMode}
                messages={messages}
                histories={histories}
                conversationId={currentConversationId}
                isRunning={isCurrentConversationRunning}
                isStopping={isCurrentConversationStopping}
              />
            )}
          </section>
        )}
      </section>
    </main>
  )
}

export default App
