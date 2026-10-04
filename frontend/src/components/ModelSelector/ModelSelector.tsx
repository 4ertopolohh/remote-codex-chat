import type { CollaborationCapability, ModelCapability } from '../../chat/useChat'
import styles from './ModelSelector.module.scss'

type Props = {
  models: ModelCapability[]
  collaborationModes: CollaborationCapability[]
  modelId: string | null
  effort: string | null
  mode: string | null
  disabled: boolean
  onModel: (id: string) => void
  onEffort: (effort: string) => void
  onMode: (mode: string | null) => void
  onRefresh: () => void
}

export function ModelSelector({ models, collaborationModes, modelId, effort, mode, disabled, onModel, onEffort, onMode, onRefresh }: Props) {
  const selected = models.find(model => model.id === modelId)
  return <div className={styles.controls}>
    {models.length > 0 && <>
      <label>Model <select value={modelId ?? ''} onChange={event => onModel(event.target.value)} disabled={disabled}>
        {models.map(model => <option key={model.id} value={model.id}>{model.display_name}</option>)}
      </select></label>
      {!!selected?.reasoning_efforts.length && <label>Reasoning <select value={effort ?? ''} onChange={event => onEffort(event.target.value)} disabled={disabled}>
        {selected.reasoning_efforts.map(value => <option key={value} value={value}>{value}</option>)}
      </select></label>}
    </>}
    {models.length > 0 && collaborationModes.some(item => item.mode !== 'default') && <label>Mode <select value={mode ?? ''} onChange={event => onMode(event.target.value || null)} disabled={disabled}>
      <option value="">Default</option>
      {collaborationModes.filter(item => item.mode !== 'default').map(item => <option key={item.mode} value={item.mode}>{item.name}</option>)}
    </select></label>}
    <button type="button" onClick={onRefresh} disabled={disabled}>Refresh models</button>
  </div>
}
