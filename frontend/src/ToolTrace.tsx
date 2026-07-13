import type { ChatMessage } from './types'

export function LoadingBubble() {
  return (
    <span className="loading-bubble" aria-label="等待回复">
      <span className="loading-dots" aria-hidden="true"><span /><span /><span /></span>
    </span>
  )
}

function ChevronDownIcon() {
  return <svg className="tool-trace-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M4.25 6.25L8 10l3.75-3.75" /></svg>
}

export function ToolTrace({ message, onToggle }: { message: ChatMessage; onToggle: (messageId: number | string) => void }) {
  const details = message.toolDetails ?? []
  if (details.length === 0) return null
  const open = Boolean(message.toolPanelOpen)
  const active = message.status === 'pending'
  const processedCount = details.length
  return (
    <div className={`tool-trace ${open ? 'open' : ''}`}>
      <button className="tool-trace-toggle" type="button" onClick={() => onToggle(message.id)}>
        <ChevronDownIcon />
        <span>{active ? '处理中' : '已处理'}</span>
        <small>{processedCount} 项</small>
      </button>
      {open && <div className="tool-trace-panel">
        {details.map((detail, index) => <section className={`tool-trace-item ${detail.kind ?? 'tool'}`} key={`${detail.label}-${index}`}>
          <div className="tool-trace-title"><span>{detail.label}</span>{detail.status && <em>{detail.status}</em>}</div>
          <pre>{detail.body}</pre>
        </section>)}
      </div>}
    </div>
  )
}
