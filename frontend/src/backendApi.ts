import type {
  B1WorkspaceSnapshot,
  B2SkillRunResponse,
  B2SkillsResponse,
  B3ToolCallsPreviewResponse,
  B3ToolsSchemaResponse,
  B5MemorySnapshot,
  B5RecallPreviewResponse,
  BackendConversation,
  BackendMessage,
  ConversationPrompt,
  UploadedFilePayload,
} from './types'

type StreamResponse = Response & { body: ReadableStream<Uint8Array> }

function apiUrl(apiBase: string, path: string) {
  return `${apiBase}${path}`
}

async function jsonOrNull(response: Response) {
  return response.json().catch(() => null)
}

export async function fetchConversationList(apiBase: string) {
  const response = await fetch(apiUrl(apiBase, '/api/conversations'))
  if (!response.ok) return null
  return (await response.json()) as BackendConversation[]
}

export async function fetchConversationMessages(apiBase: string, conversationId: string) {
  const response = await fetch(apiUrl(apiBase, `/api/conversations/${encodeURIComponent(conversationId)}`))
  if (!response.ok) return null
  return (await response.json()) as { messages: BackendMessage[] }
}

export async function deleteBackendConversation(apiBase: string, conversationId: string) {
  const response = await fetch(apiUrl(apiBase, `/api/conversations/${encodeURIComponent(conversationId)}`), {
    method: 'DELETE',
  })
  if (!response.ok) {
    const payload = await jsonOrNull(response)
    const detail = payload?.detail ?? `HTTP ${response.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
}

export async function fetchDefaultPrompt(apiBase: string) {
  const response = await fetch(apiUrl(apiBase, '/api/prompts/default'))
  if (!response.ok) return null
  return (await response.json()) as ConversationPrompt
}

export async function fetchConversationPrompt(apiBase: string, conversationId: string) {
  const response = await fetch(apiUrl(apiBase, `/api/conversations/${encodeURIComponent(conversationId)}/prompt`))
  if (!response.ok) return null
  return (await response.json()) as ConversationPrompt
}

export async function updateBackendConversationPrompt(apiBase: string, conversationId: string, content: string) {
  const response = await fetch(apiUrl(apiBase, `/api/conversations/${encodeURIComponent(conversationId)}/prompt`), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
  if (!response.ok) {
    const payload = await jsonOrNull(response)
    const detail = payload?.detail ?? `HTTP ${response.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return (await response.json()) as ConversationPrompt
}

export async function fetchB2Skills(apiBase: string, toolset = 'basic_tools') {
  const response = await fetch(apiUrl(apiBase, `/api/b2/skills?toolset=${encodeURIComponent(toolset)}`))
  if (!response.ok) {
    const payload = await jsonOrNull(response)
    const detail = payload?.detail ?? `HTTP ${response.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return (await response.json()) as B2SkillsResponse
}

export async function fetchB1WorkspaceSnapshot(apiBase: string, conversationId: string) {
  const response = await fetch(apiUrl(apiBase, `/api/b1/conversations/${encodeURIComponent(conversationId)}/workspace`))
  if (!response.ok) {
    const payload = await jsonOrNull(response)
    const detail = payload?.detail ?? `HTTP ${response.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return (await response.json()) as B1WorkspaceSnapshot
}

export async function runB2SkillPreview(
  apiBase: string,
  skillName: string,
  input: Record<string, unknown>,
  toolset = 'basic_tools',
) {
  const response = await fetch(apiUrl(apiBase, '/api/b2/skills/run'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ skill_name: skillName, input, toolset }),
  })
  if (!response.ok) {
    const payload = await jsonOrNull(response)
    const detail = payload?.detail ?? `HTTP ${response.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return (await response.json()) as B2SkillRunResponse
}

export async function fetchB3ToolsSchema(apiBase: string, toolset = 'basic_tools') {
  const response = await fetch(apiUrl(apiBase, `/api/b3/tools-schema?toolset=${encodeURIComponent(toolset)}`))
  if (!response.ok) {
    const payload = await jsonOrNull(response)
    const detail = payload?.detail ?? `HTTP ${response.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return (await response.json()) as B3ToolsSchemaResponse
}

export async function runB3ToolCallsPreview(
  apiBase: string,
  aiMessage: Record<string, unknown>,
  toolset = 'basic_tools',
) {
  const response = await fetch(apiUrl(apiBase, '/api/b3/tool-calls/preview'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ai_message: aiMessage, toolset }),
  })
  if (!response.ok) {
    const payload = await jsonOrNull(response)
    const detail = payload?.detail ?? `HTTP ${response.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return (await response.json()) as B3ToolCallsPreviewResponse
}

export async function fetchB5MemorySnapshot(apiBase: string, conversationId: string) {
  const response = await fetch(apiUrl(apiBase, `/api/b5/conversations/${encodeURIComponent(conversationId)}/memory`))
  if (!response.ok) {
    const payload = await jsonOrNull(response)
    const detail = payload?.detail ?? `HTTP ${response.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return (await response.json()) as B5MemorySnapshot
}

export async function runB5RecallPreview(apiBase: string, conversationId: string, currentUserInput: string) {
  const response = await fetch(apiUrl(apiBase, `/api/b5/conversations/${encodeURIComponent(conversationId)}/recall-preview`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_user_input: currentUserInput }),
  })
  if (!response.ok) {
    const payload = await jsonOrNull(response)
    const detail = payload?.detail ?? `HTTP ${response.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return (await response.json()) as B5RecallPreviewResponse
}

export async function requestConversationCancel(apiBase: string, conversationId: string) {
  const response = await fetch(apiUrl(apiBase, `/api/conversations/${encodeURIComponent(conversationId)}/cancel`), {
    method: 'POST',
  })
  const payload = await jsonOrNull(response)
  return Boolean(response.ok && payload?.cancel_requested)
}

export async function startRunStream(
  apiBase: string,
  body: {
    user_input: string
    conversation_id: string
    system_prompt?: string
    uploaded_file_payloads: UploadedFilePayload[]
  },
  signal: AbortSignal,
): Promise<StreamResponse> {
  const response = await fetch(apiUrl(apiBase, '/api/run/stream'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) {
    const payload = await jsonOrNull(response)
    const detail = payload?.detail ?? `HTTP ${response.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (!response.body) {
    throw new Error('浏览器没有返回可读的流式响应')
  }
  return response as StreamResponse
}

export async function startResumeStream(
  apiBase: string,
  conversationId: string,
  assistantMessageId: number | string,
  signal: AbortSignal,
): Promise<StreamResponse> {
  const response = await fetch(
    apiUrl(
      apiBase,
      `/api/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(String(assistantMessageId))}/resume`,
    ),
    {
      method: 'POST',
      signal,
    },
  )
  if (!response.ok) {
    const payload = await jsonOrNull(response)
    const detail = payload?.detail ?? `HTTP ${response.status}`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (!response.body) {
    throw new Error('浏览器没有返回可读的流式响应')
  }
  return response as StreamResponse
}
