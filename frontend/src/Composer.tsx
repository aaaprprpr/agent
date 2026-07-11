import type { ChangeEventHandler, KeyboardEventHandler, RefObject } from 'react'

import { FileTypeIcon, formatSize } from './fileUtils'
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
}: {
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
}) {
  return (
    <section className="composer-wrap">
      {dragActive && <div className="drop-hint">释放文件</div>}
      <div className="composer">
        {attachments.length > 0 && <div className="attachment-row">
          {attachments.map((file) => <div className="attachment-chip" key={file.id}>
            <FileTypeIcon name={file.name} />
            <span><strong>{file.name}</strong><small>{formatSize(file.size)}</small></span>
            <button type="button" aria-label={`移除 ${file.name}`} onClick={() => onRemoveAttachment(file.id)}>×</button>
          </div>)}
        </div>}
        <div className="composer-main">
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
          <button className="send-button" type="button" disabled={!canSend} aria-label="发送" onClick={onSend}>
            <span aria-hidden="true">↑</span>
          </button>
          <input ref={fileRef} type="file" multiple hidden onChange={onFileChange} />
        </div>
      </div>
    </section>
  )
}
