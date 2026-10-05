import type { UsageLimit as UsageLimitData } from '../../chat/useChat'
import styles from './UsageLimit.module.scss'

type Props = { label: string; limit: UsageLimitData }

export function UsageLimit({ label, limit }: Props) {
  return <li className={styles.limit}>
    <strong>{limit.limit_name ?? label}</strong>
    {(['primary', 'secondary'] as const).map(slot => {
      const window = limit[slot]
      if (!window) return null
      return <div key={slot} className={styles.window}>
        <span>{slot === 'primary' ? 'Primary' : 'Secondary'}</span>
        {window.used_percent !== undefined && <strong>{window.used_percent}% used</strong>}
        {window.window_duration_mins !== undefined && <span>{window.window_duration_mins} min window</span>}
        {window.resets_at !== undefined && <span>Resets {new Date(window.resets_at * 1000).toLocaleString()}</span>}
      </div>
    })}
    {!limit.primary && !limit.secondary && <span>Window details unavailable</span>}
  </li>
}
