import { Trash2 } from 'lucide-react'

import { MODULE_VIEWS } from './appNavigation'
import type { ActiveViewId, ModuleViewId } from './appNavigation'
import type { HistoryItem } from './types'

type AppSidebarProps = {
  activeView: ActiveViewId
  cancellingConversationIds: Set<string>
  currentConversationId: string | null
  histories: HistoryItem[]
  runningConversationIds: Set<string>
  sidebarCollapsed: boolean
  onDeleteConversation: (conversationId: string) => void
  onNewChat: () => void
  onOpenConversation: (conversationId: string) => void
  onSelectModule: (moduleId: ModuleViewId) => void
  onToggleSidebar: () => void
}

export function AppSidebar({
  activeView,
  cancellingConversationIds,
  currentConversationId,
  histories,
  runningConversationIds,
  sidebarCollapsed,
  onDeleteConversation,
  onNewChat,
  onOpenConversation,
  onSelectModule,
  onToggleSidebar,
}: AppSidebarProps) {
  return (
    <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-top">
        <button
          className="icon-button"
          type="button"
          aria-label="折叠侧栏"
          onClick={onToggleSidebar}
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
            onClick={() => onSelectModule(item.id)}
          >
            <span>{item.label}</span>
            <small>{item.title}</small>
          </button>
        ))}
      </div>

      <button
        className="new-chat"
        type="button"
        onClick={onNewChat}
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
              onClick={() => onOpenConversation(item.id)}
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
              onClick={() => onDeleteConversation(item.id)}
            >
              <Trash2 size={15} strokeWidth={1.8} aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </aside>
  )
}
