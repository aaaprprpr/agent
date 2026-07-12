import type { ClipboardEvent, RefObject, UIEventHandler } from 'react'

import { FileTypeIcon, formatSize } from './fileUtils'
import { MarkdownMessage } from './MarkdownMessage'
import { LoadingBubble, ToolTrace } from './ToolTrace'
import type { ChatMessage, GeneratedArtifact } from './types'


function handleMessageCopy(event: ClipboardEvent<HTMLDivElement>) {
  const selectedText = window.getSelection()?.toString()
  if (!selectedText) return
  const normalized = selectedText.replace(/^(?:\r?\n)+|(?:\r?\n)+$/g, '')
  event.clipboardData.setData('text/plain', normalized)
  event.preventDefault()
}


function artifactHref(downloadUrl: string, apiBase: string) {
  if (/^https?:\/\//i.test(downloadUrl)) return downloadUrl
  if (downloadUrl.startsWith('/')) return `${apiBase.replace(/\/$/, '')}${downloadUrl}`
  return downloadUrl
}


function ArtifactList({ artifacts, apiBase }: { artifacts: GeneratedArtifact[]; apiBase: string }) {
  if (artifacts.length === 0) return null
  return (
    <div className="message-artifacts">
      {artifacts.map((artifact) => (
        <a
          className="message-artifact"
          href={artifactHref(artifact.download_url, apiBase)}
          download={artifact.filename}
          key={artifact.download_url}
        >
          <FileTypeIcon name={artifact.filename} />
          <span>
            <strong>{artifact.filename}</strong>
            {typeof artifact.num_bytes === 'number' && <small>{formatSize(artifact.num_bytes)}</small>}
          </span>
          <em>下载</em>
        </a>
      ))}
    </div>
  )
}


export function ChatMessageList({
  messages,
  apiBase,
  conversationRef,
  onScroll,
  onToggleTool,
}: {
  messages: ChatMessage[]
  apiBase: string
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
              : message.role === 'assistant'
                ? <MarkdownMessage text={message.body} />
                : <p>{message.body}</p>}
            {message.role === 'assistant' && message.artifacts && (
              <ArtifactList artifacts={message.artifacts} apiBase={apiBase} />
            )}
          </div>
        </article>
      ))}
    </section>
  )
}
