export const MODULE_VIEWS = [
  { id: 'b1', label: 'B1', title: 'Agent运行与消息管理模块' },
  { id: 'b2', label: 'B2', title: 'Skill工具函数模块' },
  { id: 'b3', label: 'B3', title: '说明生成与工具调用模块' },
  { id: 'b4', label: 'B4', title: 'Agent LLM决策模块' },
  { id: 'b5', label: 'B5', title: '记忆文档存储与查找模块' },
] as const

export type ModuleView = (typeof MODULE_VIEWS)[number]
export type ModuleViewId = ModuleView['id']
export type ActiveViewId = 'chat' | ModuleViewId
export type ModuleMode = 'observe' | 'demo'

export const DEFAULT_MODULE_MODES: Record<ModuleViewId, ModuleMode> = {
  b1: 'observe',
  b2: 'observe',
  b3: 'observe',
  b4: 'observe',
  b5: 'observe',
}
