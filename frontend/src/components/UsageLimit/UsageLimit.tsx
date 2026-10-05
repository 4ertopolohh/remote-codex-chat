import type { UsageLimit as UsageLimitData } from '../../chat/useChat'
import { formatRussianDuration } from '../../localization'
import styles from './UsageLimit.module.scss'

type Props = { label: string; limit: UsageLimitData }

export function UsageLimit({ label, limit }: Props) {
  return <li className={styles.limit}>
    <strong>{limit.limit_name ?? label}</strong>
    {(['primary', 'secondary'] as const).map(slot => {
      const window = limit[slot]
      if (!window) return null
      return <div key={slot} className={styles.window}>
        <span>{slot === 'primary' ? 'Основной лимит' : 'Недельный лимит'}</span>
        {window.used_percent !== undefined && <strong>Осталось: {Math.max(0, 100 - window.used_percent)}%</strong>}
        {window.window_duration_mins !== undefined && <span>Период: {formatRussianDuration(window.window_duration_mins)}</span>}
        {window.resets_at !== undefined && <span>Сброс: {new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(window.resets_at * 1000))}</span>}
      </div>
    })}
    {!limit.primary && !limit.secondary && <span>Сведения о лимитах недоступны.</span>}
  </li>
}
