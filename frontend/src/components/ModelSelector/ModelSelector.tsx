import type { CollaborationCapability, ModelCapability } from '../../chat/useChat'
import { SelectControl } from '../SelectControl/SelectControl'
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
      <SelectControl label="Model" value={modelId ?? ''} options={models.map(model => ({ value: model.id, label: model.display_name }))} onChange={onModel} disabled={disabled} />
      {!!selected?.reasoning_efforts.length && <SelectControl label="Reasoning" value={effort ?? ''} options={selected.reasoning_efforts.map(value => ({ value, label: value }))} onChange={onEffort} disabled={disabled} />}
    </>}
    {models.length > 0 && collaborationModes.some(item => item.mode !== 'default') && <SelectControl label="Mode" value={mode ?? ''} options={[{ value: '', label: 'Default' }, ...collaborationModes.filter(item => item.mode !== 'default').map(item => ({ value: item.mode, label: item.name }))]} onChange={value => onMode(value || null)} disabled={disabled} />}
    <button type="button" onClick={onRefresh} disabled={disabled}>Refresh models</button>
  </div>
}
