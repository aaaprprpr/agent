import { Braces, Radio, ServerCog } from 'lucide-react'
import { prettyValue, statusClass } from './moduleViewUtils'
import type { B4ModelInfo } from './types'

const STAGE_LABELS: Record<string, string> = {
  planning: '规划',
  tool_calling: '工具决策',
  observation: '观察',
  answering: '最终回答',
  failure_answering: '失败收束',
  memory_reflection: '记忆反思',
  b5_memory_rerank: '记忆重排',
}

const KIND_LABELS: Record<string, string> = {
  model: '模型调用',
  stream: '流式调用',
  parser: '协议解析',
}

const SCOPE_LABELS: Record<string, string> = {
  agent_runtime: 'Agent 主链路',
  memory_support: '记忆辅助调用',
  standalone: '独立调用',
}

export function stageLabel(stage: string) {
  return STAGE_LABELS[stage] ?? stage
}

export function kindLabel(kind: string) {
  return KIND_LABELS[kind] ?? kind
}

export function scopeLabel(scope: string) {
  return SCOPE_LABELS[scope] ?? scope
}

export function CaseKindIcon({ kind }: { kind: string }) {
  if (kind === 'stream') return <Radio size={14} aria-hidden="true" />
  if (kind === 'parser') return <Braces size={14} aria-hidden="true" />
  return <ServerCog size={14} aria-hidden="true" />
}

export function CodePanel({ title, value, muted = false }: { title: string; value: unknown; muted?: boolean }) {
  return (
    <section className={`b4-code-panel ${muted ? 'is-muted' : ''}`}>
      <h3>{title}</h3>
      <pre>{prettyValue(value)}</pre>
    </section>
  )
}

function modelValue(value: string | null | undefined, fallback = '未配置') {
  return value && value.trim() ? value : fallback
}

export function ModelConfigBar({ model }: { model?: B4ModelInfo }) {
  return (
    <dl className="b4-model-bar">
      <div>
        <dt>模型来源</dt>
        <dd>{modelValue(model?.source, '读取中')}</dd>
      </div>
      <div>
        <dt>模型</dt>
        <dd title={modelValue(model?.model)}>{modelValue(model?.model)}</dd>
      </div>
      <div>
        <dt>运行模式</dt>
        <dd>{modelValue(model?.mode)}</dd>
      </div>
      <div>
        <dt>工具绑定</dt>
        <dd>{modelValue(model?.tool_binding)}</dd>
      </div>
      <div>
        <dt>配置</dt>
        <dd>{modelValue(model?.config_path, 'configs/model.yaml')}</dd>
      </div>
    </dl>
  )
}

export function StatusMark({ status }: { status: string }) {
  return <span className={`b4-status-mark ${statusClass(status)}`}>{status}</span>
}
