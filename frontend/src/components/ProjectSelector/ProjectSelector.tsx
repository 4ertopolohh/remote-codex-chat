import type { ProjectInfo } from '../../chat/useChat'
import { SelectControl } from '../SelectControl/SelectControl'
import styles from './ProjectSelector.module.scss'

type Props = {
  projects: ProjectInfo[]
  selectedId: string | null
  disabled: boolean
  onSelect: (id: string) => void
}

export function ProjectSelector({ projects, selectedId, disabled, onSelect }: Props) {
  if (projects.length === 0) return null
  const options = projects.map(project => ({ value: project.id, label: project.name }))
  if (selectedId === null) options.unshift({ value: '', label: 'Выберите проект' })
  return <SelectControl label="Проект" value={selectedId ?? ''} options={options} disabled={disabled} onChange={onSelect} className={styles.project} />
}
