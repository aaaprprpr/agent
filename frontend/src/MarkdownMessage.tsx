import type { ReactNode } from 'react'

type MarkdownBlock =
  | { type: 'code'; language: string; content: string }
  | { type: 'text'; content: string }

function parseBlocks(text: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = []
  const fencePattern = /(^|\n)(```|''')([A-Za-z0-9_+-]*)[ \t]*\n([\s\S]*?)(?:\n\2(?=\n|$)|$)/g
  let cursor = 0
  let match: RegExpExecArray | null

  while ((match = fencePattern.exec(text)) !== null) {
    const fenceStart = match.index + match[1].length
    if (fenceStart > cursor) {
      blocks.push({ type: 'text', content: text.slice(cursor, fenceStart) })
    }
    blocks.push({
      type: 'code',
      language: match[3].trim().toLowerCase(),
      content: match[4].replace(/\n$/, ''),
    })
    cursor = fencePattern.lastIndex
  }

  if (cursor < text.length) {
    blocks.push({ type: 'text', content: text.slice(cursor) })
  }
  return blocks.length ? blocks : [{ type: 'text', content: text }]
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*\n]+\*|_[^_\n]+_)/g
  let cursor = 0
  let index = 0
  let match: RegExpExecArray | null

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index))
    const token = match[0]
    const key = `${keyPrefix}-${index}`
    if (token.startsWith('`') && token.endsWith('`')) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>)
    } else if ((token.startsWith('**') && token.endsWith('**')) || (token.startsWith('__') && token.endsWith('__'))) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>)
    } else {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>)
    }
    cursor = pattern.lastIndex
    index += 1
  }

  if (cursor < text.length) nodes.push(text.slice(cursor))
  return nodes
}

function renderTextBlock(content: string, blockIndex: number) {
  const lines = content.replace(/\r\n/g, '\n').split('\n')
  const elements: ReactNode[] = []
  let paragraph: string[] = []
  let list: Array<{ ordered: boolean; text: string }> = []

  function flushParagraph() {
    if (!paragraph.length) return
    const text = paragraph.join('\n').trim()
    if (text) {
      elements.push(
        <p key={`p-${blockIndex}-${elements.length}`}>
          {renderInline(text, `p-${blockIndex}-${elements.length}`)}
        </p>,
      )
    }
    paragraph = []
  }

  function flushList() {
    if (!list.length) return
    const ordered = list.every((item) => item.ordered)
    const items = list.map((item, index) => (
      <li key={`li-${blockIndex}-${elements.length}-${index}`}>
        {renderInline(item.text, `li-${blockIndex}-${elements.length}-${index}`)}
      </li>
    ))
    elements.push(
      ordered
        ? <ol key={`ol-${blockIndex}-${elements.length}`}>{items}</ol>
        : <ul key={`ul-${blockIndex}-${elements.length}`}>{items}</ul>,
    )
    list = []
  }

  function pushHeading(level: number, text: string) {
    const key = `h-${blockIndex}-${elements.length}`
    const children = renderInline(text, key)
    if (level === 1) elements.push(<h1 key={key}>{children}</h1>)
    else if (level === 2) elements.push(<h2 key={key}>{children}</h2>)
    else if (level === 3) elements.push(<h3 key={key}>{children}</h3>)
    else elements.push(<h4 key={key}>{children}</h4>)
  }

  lines.forEach((line) => {
    const trimmed = line.trim()
    if (!trimmed) {
      flushParagraph()
      flushList()
      return
    }

    const heading = /^(#{1,4})\s+(.+)$/.exec(trimmed)
    if (heading) {
      flushParagraph()
      flushList()
      const level = Math.min(heading[1].length, 4)
      pushHeading(level, heading[2])
      return
    }

    const bullet = /^[-*]\s+(.+)$/.exec(trimmed)
    const numbered = /^\d+[.)]\s+(.+)$/.exec(trimmed)
    if (bullet || numbered) {
      flushParagraph()
      const ordered = Boolean(numbered)
      if (list.length && list[list.length - 1].ordered !== ordered) flushList()
      list.push({ ordered, text: (bullet ?? numbered)?.[1] ?? trimmed })
      return
    }

    flushList()
    paragraph.push(line)
  })

  flushParagraph()
  flushList()
  return elements
}

export function MarkdownMessage({ text }: { text: string }) {
  const blocks = parseBlocks(text)
  return (
    <div className="markdown-message">
      {blocks.map((block, index) => {
        if (block.type === 'code') {
          return (
            <div className="markdown-code-block" key={`code-${index}`}>
              {block.language && <div className="markdown-code-lang">{block.language}</div>}
              <pre><code>{block.content}</code></pre>
            </div>
          )
        }
        return <div key={`text-${index}`}>{renderTextBlock(block.content, index)}</div>
      })}
    </div>
  )
}
