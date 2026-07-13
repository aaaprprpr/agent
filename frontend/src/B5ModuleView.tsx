import { Archive, Database, FileText, Layers, Search, Split, TextSelect } from 'lucide-react'

type ModuleMode = 'observe' | 'demo'

type B5ModuleViewProps = {
  mode: ModuleMode
}

type DemoTurn = {
  id: number
  user: string
  assistant: string
  toolCount: number
  summary: string
  labels: string[]
}

type DemoBlock = {
  id: string
  start: number
  end: number
  title: string
  summary: string
}

const DEMO_TURNS: DemoTurn[] = [
  {
    id: 1,
    user: '上传 IPv6 开放课题文档，要求总结并生成文档。',
    assistant: '读取 docx，提取课题需求，生成总结文件。',
    toolCount: 2,
    summary: '围绕上传文档完成读取、摘要与 docx 生成。',
    labels: ['file:docx', 'task_state'],
  },
  {
    id: 2,
    user: '要求把下载链接从正文里移出去。',
    assistant: '调整前端附件卡片展示，正文只保留自然回复。',
    toolCount: 0,
    summary: '用户确认下载附件应作为结构化产物独立展示。',
    labels: ['preference', 'ui'],
  },
  {
    id: 3,
    user: '检查 B1 的基础能力和 max_turns。',
    assistant: '恢复 max_turns=10，并保留当前 workspace 链路。',
    toolCount: 1,
    summary: 'B1 验收链路需要保留 max_turns，默认设为 10。',
    labels: ['b1', 'requirement'],
  },
  {
    id: 4,
    user: '设计五个模块的验收界面。',
    assistant: '添加模块切换，逐步制作 B1/B2/B3/B5 观察页。',
    toolCount: 0,
    summary: '前端进入模块验收展示阶段，侧边栏保留历史对话。',
    labels: ['frontend', 'demo'],
  },
]

const DEMO_BLOCKS: DemoBlock[] = [
  {
    id: 'block_001',
    start: 1,
    end: 2,
    title: '文件生成与附件展示',
    summary: '覆盖上传文件读取、生成文件、下载附件独立展示的连续需求。',
  },
  {
    id: 'block_002',
    start: 3,
    end: 4,
    title: '模块验收界面整理',
    summary: '覆盖 B1 验收能力检查和模块观察页设计。',
  },
]

const RECALL_HITS = [
  { type: 'task', title: '模块验收界面整理', score: '0.91', source: 'task_memory' },
  { type: 'turn', title: 'B1 max_turns 验收要求', score: '0.84', source: 'turn_summary #3' },
  { type: 'block', title: '文件生成与附件展示', score: '0.72', source: 'memory_block #1' },
]

const CONTEXT_LINES = [
  '[B5 memory context]',
  '当前任务：整理五个模块的验收展示界面。',
  '最近原始历史：保留最后若干轮 user/assistant 消息。',
  '召回摘要：B1 需要展示消息管控、workspace、memory context；B5 需要展示历史对话、压缩和召回。',
  '策略：摘要只作为定位线索，精确事实以 source message/tool step 为准。',
]

function ObservationPanel() {
  const totalTools = DEMO_TURNS.reduce((sum, turn) => sum + turn.toolCount, 0)

  return (
    <div className="b5-module">
      <header className="b5-head">
        <div>
          <span>B5</span>
          <h2>记忆文档存储与查找模块</h2>
        </div>
        <div className="b5-summary">
          <span>{DEMO_TURNS.length} 轮</span>
          <span>{DEMO_BLOCKS.length} 块压缩</span>
          <span>{totalTools} 个工具引用</span>
        </div>
      </header>

      <div className="b5-layout">
        <section className="b5-history-panel" aria-label="历史记录与压缩">
          <div className="b5-panel-title">
            <Database size={15} strokeWidth={1.9} aria-hidden="true" />
            <strong>历史记录与压缩</strong>
          </div>

          <div
            className="b5-compression-board"
            style={{ gridTemplateRows: `34px repeat(${DEMO_TURNS.length}, minmax(104px, auto))` }}
          >
            <div className="b5-board-head db">全量数据库</div>
            <div className="b5-board-head turn">轮对话压缩</div>
            <div className="b5-board-head block">块级压缩</div>

            {DEMO_TURNS.map((turn, index) => (
              <article
                className="b5-db-turn"
                key={`db-${turn.id}`}
                style={{ gridColumn: 1, gridRow: index + 2 }}
              >
                <header>
                  <span>turn {turn.id}</span>
                  <em>{turn.toolCount} tool</em>
                </header>
                <p><strong>用户</strong>{turn.user}</p>
                <p><strong>AI</strong>{turn.assistant}</p>
              </article>
            ))}

            {DEMO_TURNS.map((turn, index) => (
              <article
                className="b5-turn-summary"
                key={`summary-${turn.id}`}
                style={{ gridColumn: 2, gridRow: index + 2 }}
              >
                <header>
                  <FileText size={14} strokeWidth={1.9} aria-hidden="true" />
                  <strong>turn_summary</strong>
                </header>
                <p>{turn.summary}</p>
                <div className="b5-tags">
                  {turn.labels.map((label) => <span key={label}>{label}</span>)}
                </div>
              </article>
            ))}

            {DEMO_BLOCKS.map((block) => (
              <article
                className="b5-block-card"
                key={block.id}
                style={{ gridColumn: 3, gridRow: `${block.start + 1} / ${block.end + 2}` }}
              >
                <div className="b5-block-range" aria-hidden="true">
                  <span />
                </div>
                <div>
                  <header>
                    <Archive size={14} strokeWidth={1.9} aria-hidden="true" />
                    <strong>{block.title}</strong>
                  </header>
                  <small>turn {block.start}-{block.end}</small>
                  <p>{block.summary}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="b5-recall-panel" aria-label="召回与上下文">
          <div className="b5-panel-title">
            <Search size={15} strokeWidth={1.9} aria-hidden="true" />
            <strong>召回与上下文</strong>
          </div>

          <div className="b5-recall-flow">
            <div><TextSelect size={15} /><strong>当前输入</strong><span>query text</span></div>
            <div><Layers size={15} /><strong>候选池</strong><span>blocks / turns</span></div>
            <div><Search size={15} /><strong>召回命中</strong><span>score 排序</span></div>
            <div><Split size={15} /><strong>源证据</strong><span>messages / steps</span></div>
            <div><Database size={15} /><strong>B1 上下文</strong><span>memory_messages</span></div>
          </div>

          <div className="b5-recall-detail">
            <section className="b5-hit-list">
              <h3>召回内容</h3>
              {RECALL_HITS.map((hit) => (
                <article key={`${hit.type}-${hit.title}`}>
                  <header>
                    <span>{hit.type}</span>
                    <em>{hit.score}</em>
                  </header>
                  <strong>{hit.title}</strong>
                  <p>{hit.source}</p>
                </article>
              ))}
            </section>

            <section className="b5-context-box">
              <h3>拼给 B1 的上下文</h3>
              <div className="b5-context-meta">
                <span>context_chars 286</span>
                <span>truncated false</span>
                <span>recent raw history 4</span>
              </div>
              <pre>{CONTEXT_LINES.join('\n')}</pre>
            </section>
          </div>
        </section>
      </div>
    </div>
  )
}

function DemoPanel() {
  return (
    <div className="b5-module">
      <header className="b5-head">
        <div>
          <span>B5</span>
          <h2>单模块演示输入</h2>
        </div>
        <strong>未执行</strong>
      </header>

      <div className="b5-demo-grid">
        <section className="b5-demo-card">
          <h3>构造召回输入</h3>
          <label>
            conversation_id
            <input defaultValue="conv_web_demo" />
          </label>
          <label>
            current_user_input
            <textarea defaultValue="继续设计 B5 验收界面，展示历史对话压缩和召回上下文。" />
          </label>
          <button type="button" disabled>运行演示</button>
        </section>

        <section className="b5-demo-card">
          <h3>输入预览</h3>
          <pre>{JSON.stringify({
            operation: 'prepare_workspace_memory_context',
            conversation_id: 'conv_web_demo',
            current_user_input: '继续设计 B5 验收界面，展示历史对话压缩和召回上下文。',
          }, null, 2)}</pre>
        </section>
      </div>
    </div>
  )
}

export function B5ModuleView({ mode }: B5ModuleViewProps) {
  return mode === 'observe' ? <ObservationPanel /> : <DemoPanel />
}
