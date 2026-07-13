import type { ChangeEventHandler, KeyboardEventHandler, RefObject } from 'react'
import { ArrowUp, ChevronDown, ChevronUp, Square } from 'lucide-react'

import { formatSize } from './fileDataUtils'
import { FileTypeIcon } from './fileUtils'
import type { Attachment } from './types'


export function Composer({
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
  isRunning,
  isStopping,
  onStop,
  promptOpen,
  systemPrompt,
  onPromptToggle,
  onPromptSave,
  onSystemPromptChange,
}: {
  attachments: Attachment[]
  dragActive: boolean
  draft: string
  canSend: boolean
  isRunning: boolean
  isStopping: boolean
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
}) {
  const actionLabel = isStopping ? '正在终止' : isRunning ? '终止回答' : '发送'

  return (
    <section className="composer-wrap">
      {dragActive && <div className="drop-hint">释放文件</div>}
      <div className="composer">
        {promptOpen && (
          <div className="system-prompt-panel">
            <div className="system-prompt-head">
              <strong>系统提示词</strong>
              <span>当前对话副本</span>
            </div>
            <div className="system-prompt-editor">
              <textarea
                value={systemPrompt}
                spellCheck={false}
                placeholder="正在读取当前对话的系统提示词..."
                onChange={(event) => onSystemPromptChange(event.target.value)}
              />
              <button className="system-prompt-save" type="button" onClick={onPromptSave}>
                保存
              </button>
            </div>
          </div>
        )}
        {attachments.length > 0 && <div className="attachment-row">
          {attachments.map((file) => <div className="attachment-chip" key={file.id}>
            <FileTypeIcon name={file.name} />
            <span><strong>{file.name}</strong><small>{formatSize(file.size)}</small></span>
            <button type="button" aria-label={`移除 ${file.name}`} onClick={() => onRemoveAttachment(file.id)}>×</button>
          </div>)}
        </div>}
        <div className="composer-main">
          <button
            className="prompt-toggle-button"
            type="button"
            aria-label={promptOpen ? '收起系统提示词' : '展开系统提示词'}
            title={promptOpen ? '收起系统提示词' : '展开系统提示词'}
            onClick={onPromptToggle}
          >
            {promptOpen ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronUp size={16} aria-hidden="true" />}
          </button>
          <button className="tool-button" type="button" aria-label="添加文件" onClick={() => fileRef.current?.click()}>
            <span aria-hidden="true">＋</span>
          </button>
          <textarea
            ref={inputRef}
            value={draft}
            rows={1}
            autoComplete="off"
            spellCheck={false}
            placeholder="输入任务..."
            onChange={(event) => onDraftChange(event.target.value)}
            onKeyDown={onKeyDown}
          />
          <button
            className={`send-button ${isRunning ? 'stop' : ''}`}
            type="button"
            disabled={isStopping || (!isRunning && !canSend)}
            aria-label={actionLabel}
            title={actionLabel}
            onClick={isRunning && !isStopping ? onStop : onSend}
          >
            {isRunning ? <Square size={14} fill="currentColor" aria-hidden="true" /> : <ArrowUp size={18} aria-hidden="true" />}
          </button>
          <input ref={fileRef} type="file" multiple hidden onChange={onFileChange} />
        </div>
      </div>
    </section>
  )
}
