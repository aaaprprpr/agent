import type { ModuleMode } from './appNavigation'
import { B4DemoPanel } from './B4DemoPanel'
import { B4ObservationPanel } from './B4ObservationPanel'

type B4ModuleViewProps = {
  mode: ModuleMode
  conversationId: string | null
}

export function B4ModuleView({ mode, conversationId }: B4ModuleViewProps) {
  return mode === 'observe' ? <B4ObservationPanel conversationId={conversationId} /> : <B4DemoPanel />
}
