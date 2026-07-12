export type Role = 'user' | 'assistant' | 'tool'

export type MessageAttachment = {
  name: string
  size: number
  path?: string
}

export type ToolDetail = {
  label: string
  body: string
  status?: string
  kind?: 'note' | 'tool' | 'agent'
}

export type ChatMessage = {
  id: number | string
  role: Role
  body: string
  status?: 'pending' | 'error'
  toolDetails?: ToolDetail[]
  toolPanelOpen?: boolean
  attachments?: MessageAttachment[]
}

export type Attachment = {
  id: number
  name: string
  size: number
  file: File
}

export type UploadedFilePayload = {
  name: string
  size: number
  mime_type?: string
  content_base64: string
}

export type HistoryItem = {
  id: string
  title: string
  messages: ChatMessage[]
  memoryReady: boolean
}

export type BackendConversation = {
  id: string
  title: string
}

export type BackendMessage = {
  id: string
  role: Role
  content: string
  status?: 'pending' | 'error' | null
  tool_steps?: Record<string, unknown>[]
  attachments?: MessageAttachment[]
}

export type RunStreamEvent =
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
      agent_step?: Record<string, unknown>
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
      agent_step?: Record<string, unknown>
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
