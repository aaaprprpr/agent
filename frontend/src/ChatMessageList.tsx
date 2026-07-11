import type { ClipboardEvent, RefObject, UIEventHandler } from 'react'

import { FileTypeIcon, formatSize } from './fileUtils'
import { LoadingBubble, ToolTrace } from './ToolTrace'
import type { ChatMessage } from './types'


function handleMessageCopy(event: ClipboardEvent<HTMLDivElement>) {
  const selectedText = window.getSelection()?.toString()
  if (!selectedText) return
  const normalized = selectedText.replace(/^(?:\r?\n)+|(?:\r?\n)+$/g, '')
  event.clipboardData.setData('text/plain', normalized)
  event.preventDefault()
}


export function ChatMessageList({
  messages,
  conversationRef,
  onScroll,
  onToggleTool,
}: {
  messages: ChatMessage[]
  conversationRef: RefObject<HTMLElement | null>
  onScroll: UIEventHandler<HTMLElement>
  onToggleTool: (messageId: number | string) => void
}) {
  return (
    <section className="conversation" aria-label="消息列表" ref={conversationRef} onScroll={onScroll}>
      {messages.map((message) => (
        <article className={`message ${message.role} ${message.status ?? ''}`} key={message.id}>
          <div className="message-body" onCopy={handleMessageCopy}>
            {message.role === 'assistant' && <ToolTrace message={message} onToggle={onToggleTool} />}
            {message.role === 'user' && message.attachments && message.attachments.length > 0 && (
              <div className="message-attachments">
                {message.attachments.map((file, index) => (
                  <div className="message-attachment" key={`${file.path ?? file.name}-${index}`}>
                    <FileTypeIcon name={file.name} />
                    <span><strong>{file.name}</strong><small>{formatSize(file.size)}</small></span>
                  </div>
                ))}
              </div>
            )}
            {message.status === 'pending' && (!message.body || message.body === '...')
              ? <LoadingBubble />
              : <p>{message.body}</p>}
          </div>
        </article>
      ))}
    </section>
  )
}
