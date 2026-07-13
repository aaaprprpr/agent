import type { BackendConversation, BackendMessage, UploadedFilePayload } from './types'

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
