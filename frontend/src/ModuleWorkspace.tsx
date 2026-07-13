import { B1ModuleView } from './B1ModuleView'
import { B2ModuleView } from './B2ModuleView'
import { B3ModuleView } from './B3ModuleView'
import { B4ModuleView } from './B4ModuleView'
import { B5ModuleView } from './B5ModuleView'
import type { ModuleMode, ModuleView, ModuleViewId } from './appNavigation'
import type { ChangeEventHandler, KeyboardEventHandler, RefObject } from 'react'
import type { Attachment, B1RuntimeEvent, ChatMessage, HistoryItem } from './types'

type ModuleWorkspaceProps = {
  activeModule: ModuleView | null
  activeModuleMode: ModuleMode
  conversationId: string | null
  histories: HistoryItem[]
  isRunning: boolean
  isStopping: boolean
  messages: ChatMessage[]
  runtimeEvents: B1RuntimeEvent[]
  attachments: Attachment[]
  dragActive: boolean
  draft: string
  canSend: boolean
  inputRef: RefObject<HTMLTextAreaElement | null>
  fileRef: RefObject<HTMLInputElement | null>
  onDraftChange: (value: string) => void
  onKeyDown: KeyboardEventHandler<HTMLTextAreaElement>
  onFileChange: ChangeEventHandler<HTMLInputElement>
  onRemoveAttachment: (id: number) => void
  onSend: () => void
  onStop: () => void
  promptOpen: boolean
  systemPrompt: string
  onPromptToggle: () => void
  onPromptSave: () => void
  onSystemPromptChange: (value: string) => void
  onToggleMode: (moduleId: ModuleViewId) => void
}

export function ModuleWorkspace({
  activeModule,
  activeModuleMode,
  conversationId,
  histories,
  isRunning,
  isStopping,
  messages,
  runtimeEvents,
  attachments,
  dragActive,
  draft,
  canSend,
  inputRef,
  fileRef,
  onDraftChange,
  onKeyDown,
  onFileChange,
  onRemoveAttachment,
  onSend,
  onStop,
  promptOpen,
  systemPrompt,
  onPromptToggle,
  onPromptSave,
  onSystemPromptChange,
  onToggleMode,
}: ModuleWorkspaceProps) {
  return (
    <section className="module-placeholder" aria-label={`${activeModule?.label ?? '模块'} 验收界面`}>
      {activeModule && (
        <button
          className={`module-mode-switch ${activeModuleMode === 'demo' ? 'is-demo' : ''}`}
          type="button"
          aria-label={`切换${activeModule.label}展示模式`}
          aria-pressed={activeModuleMode === 'demo'}
          onClick={() => onToggleMode(activeModule.id)}
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
          runtimeEvents={runtimeEvents}
          histories={histories}
          conversationId={conversationId}
          isRunning={isRunning}
          isStopping={isStopping}
          attachments={attachments}
          dragActive={dragActive}
          draft={draft}
          canSend={canSend}
          inputRef={inputRef}
          fileRef={fileRef}
          onDraftChange={onDraftChange}
          onKeyDown={onKeyDown}
          onFileChange={onFileChange}
          onRemoveAttachment={onRemoveAttachment}
          onSend={onSend}
          onStop={onStop}
          promptOpen={promptOpen}
          systemPrompt={systemPrompt}
          onPromptToggle={onPromptToggle}
          onPromptSave={onPromptSave}
          onSystemPromptChange={onSystemPromptChange}
        />
      )}
      {activeModule?.id === 'b2' && (
        <B2ModuleView
          mode={activeModuleMode}
          messages={messages}
        />
      )}
      {activeModule?.id === 'b3' && (
        <B3ModuleView
          mode={activeModuleMode}
          messages={messages}
        />
      )}
      {activeModule?.id === 'b4' && (
        <B4ModuleView
          mode={activeModuleMode}
          conversationId={conversationId}
        />
      )}
      {activeModule?.id === 'b5' && (
        <B5ModuleView
          mode={activeModuleMode}
          conversationId={conversationId}
        />
      )}
    </section>
  )
}
