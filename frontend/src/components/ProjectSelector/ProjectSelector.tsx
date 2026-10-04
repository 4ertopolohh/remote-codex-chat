import type { ProjectInfo } from '../../chat/useChat'
import styles from './ProjectSelector.module.scss'

type Props = {
  projects: ProjectInfo[]
  selectedId: string | null
  disabled: boolean
  onSelect: (id: string) => void
}

export function ProjectSelector({ projects, selectedId, disabled, onSelect }: Props) {
  if (projects.length === 0) return null
  return <label className={styles.control}>Project
    <select value={selectedId ?? ''} disabled={disabled} onChange={event => onSelect(event.target.value)}>
      {selectedId === null && <option value="">Select project</option>}
      {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
    </select>
  </label>
}
