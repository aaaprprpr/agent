import { artifactsFromToolSteps, toolDetailsFromSteps } from './toolTraceUtils'
import type { BackendMessage, ChatMessage } from './types'

export function backendMessagesToChatMessages(messages: BackendMessage[]) {
  return messages
    .filter((message) => message.role === 'user' || message.role === 'assistant')
    .map((message) => ({
      id: message.id,
      role: message.role,
      body: message.content,
      status: message.status ?? undefined,
      toolDetails: toolDetailsFromSteps(message.tool_steps),
      artifacts: artifactsFromToolSteps(message.tool_steps),
      attachments: message.attachments,
    })) satisfies ChatMessage[]
}
