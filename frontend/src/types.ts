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

export type GeneratedArtifact = {
  filename: string
  download_url: string
  file_type?: string
  suffix?: string
  num_bytes?: number
  relative_output_path?: string
}

export type ChatMessage = {
  id: number | string
  role: Role
  body: string
  status?: 'pending' | 'error' | 'cancelled'
  resumable?: boolean
  toolDetails?: ToolDetail[]
  toolPanelOpen?: boolean
  attachments?: MessageAttachment[]
  artifacts?: GeneratedArtifact[]
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

export type ConversationPrompt = {
  conversation_id: string
  prompt_id: string
  content: string
  default_content: string
  locked_default: boolean
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
  status?: 'pending' | 'error' | 'cancelled' | null
  resumable?: boolean
  tool_steps?: Record<string, unknown>[]
  attachments?: MessageAttachment[]
}

export type B2SkillDefinition = {
  name: string
  enabled: boolean
  module?: string
  function?: string
  description?: string
  side_effects?: boolean
  parameters?: Record<string, Record<string, unknown>>
  required?: string[]
  returns?: Record<string, Record<string, unknown>>
  parameter_count?: number
  return_count?: number
}

export type B2SkillsResponse = {
  status: string
  module: string
  toolset: string
  tool_count: number
  tools: B2SkillDefinition[]
  toolsets?: Record<string, string[]>
  settings?: Record<string, unknown>
}

export type B2SkillRunResponse = {
  status: string
  module: string
  toolset: string
  skill_name: string
  run_id: string
  output_dir: string
  result: Record<string, unknown>
}

export type B3ToolsSchemaResponse = {
  status: string
  module: string
  toolset: string
  tool_count: number
  tools: string[]
  tools_schema: Record<string, unknown>[]
  toolsets?: Record<string, string[]>
}

export type B3ToolCallsPreviewResponse = {
  status: string
  module: string
  toolset: string
  run_id: string
  output_dir: string
  tool_count: number
  tools: string[]
  tools_schema: Record<string, unknown>[]
  tool_calls: Record<string, unknown>[]
  tool_messages: Record<string, unknown>[]
  results: Record<string, unknown>[]
  summary?: Record<string, unknown>
}

export type B4ModelInfo = {
  source?: string | null
  model?: string | null
  endpoint?: string | null
  mode?: string | null
  tool_binding?: string | null
  config_path?: string | null
  available_sources?: string[]
}

export type B4CallSummary = {
  id: string
  stage: string
  scope: string
  kind: string
  status: string
  source: string
  mode: string
  generated_at?: string | null
  message_count: number
  roles: string[]
  raw_chars: number
  run_id: string
}

export type B4CallsResponse = {
  status: string
  module: string
  conversation_id?: string | null
  model?: B4ModelInfo
  calls: B4CallSummary[]
}

export type B4CallDetailResponse = {
  status: string
  module: string
  call: B4CallSummary
  record: Record<string, unknown>
  standard_output: unknown
}

export type B4ProtocolCase = {
  id: string
  title: string
  kind: string
  level: string
  description: string
  expected: string
}

export type B4ProtocolCasesResponse = {
  status: string
  module: string
  model?: B4ModelInfo
  cases: B4ProtocolCase[]
}

export type B4ProtocolResult = {
  case_id: string
  test_status: string
  verdict: string
  elapsed_ms: number
  request: Record<string, unknown>
  raw_text: string
  prompt_messages: Record<string, unknown>[]
  ai_message: Record<string, unknown> | null
  parsed_candidate: Record<string, unknown> | null
  error: Record<string, unknown> | null
  stream: {
    delta_count: number
    deltas: string[]
  }
}

export type B4ProtocolRunResponse = {
  status: string
  module: string
  run_id: string
  output_dir: string
  model?: B4ModelInfo
  summary: {
    total: number
    passed: number
    failed: number
  }
  results: B4ProtocolResult[]
}

export type B1WorkspaceSnapshot = {
  status: string
  module: string
  conversation_id: string
  checkpoint?: Record<string, unknown>
  runtime?: Record<string, unknown>
  selected_memory?: Record<string, unknown>
  tools_schema_count?: number
  workspace?: Record<string, unknown> | null
}

export type B5MemorySnapshot = {
  status: string
  conversation_id: string
  counts: Record<string, number>
  conversation?: Record<string, unknown>
  messages: Record<string, unknown>[]
  turns: Record<string, unknown>[]
  turn_summaries: Record<string, unknown>[]
  memory_blocks: Record<string, unknown>[]
  task_memories: Record<string, unknown>[]
  retrieval_logs: Record<string, unknown>[]
}

export type B5RecallPreviewRequest = {
  current_user_input: string
}

export type B5RecallPreviewResponse = {
  status: string
  conversation_id: string
  current_user_input?: string
  history_message_count?: number
  recent_history_message_count?: number
  recent_history_messages?: Record<string, unknown>[]
  workspace_memory?: Record<string, unknown>
  layered_memory_context?: Record<string, unknown>
  memory_messages?: Record<string, unknown>[]
  recalled_blocks?: Record<string, unknown>[]
  recalled_turns?: Record<string, unknown>[]
  source_messages?: Record<string, unknown>[]
  source_tool_steps?: Record<string, unknown>[]
  vector_retrieval?: unknown
  llm_rerank?: unknown
  retrieval_log?: Record<string, unknown> | null
  [key: string]: unknown
}

export type RunStreamEvent =
  | {
      type: 'start'
      conversation_id: string
      run_id?: string
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
        checkpoint?: { exists?: boolean }
      }
      tool_steps?: Record<string, unknown>[]
    }
  | {
      type: 'error'
      conversation_id?: string
      assistant_message_id?: string
      message: string
    }

export type B1RuntimeEvent = {
  id: number
  receivedAt: number
  event: RunStreamEvent
}
