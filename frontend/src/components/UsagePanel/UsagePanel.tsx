import type { Usage } from '../../chat/useChat'
import { ActionButton } from '../ActionButton/ActionButton'
import { UsageLimit } from '../UsageLimit/UsageLimit'
import styles from './UsagePanel.module.scss'

type Props = { usage: Usage | null; onRefresh: () => void; connected: boolean }

export function UsagePanel({ usage, onRefresh, connected }: Props) {
  const entries = usage ? Object.entries(usage.rate_limits_by_id) : []
  return <section className={styles.panel} aria-label="Использование и лимиты">
    <div className={styles.heading}><h2>Использование</h2><ActionButton tone="secondary" onClick={onRefresh} disabled={!connected}>Обновить</ActionButton></div>
    {!usage && <p>Загружаем сведения…</p>}
    {usage?.status === 'unsupported' && <p>Эта версия Codex не предоставляет сведения об использовании.</p>}
    {usage?.status === 'error' && <p>Сведения об использовании недоступны.</p>}
    {usage?.status === 'available' && <>
      {usage.ordinary_usage_allowed !== null && <p>{usage.ordinary_usage_allowed ? 'Обычное использование доступно' : 'Обычное использование недоступно'}</p>}
      {usage.rate_limits && (entries.length === 0 || !usage.rate_limits.limit_id || !usage.rate_limits_by_id[usage.rate_limits.limit_id]) && <ul><UsageLimit label="Лимиты аккаунта" limit={usage.rate_limits} /></ul>}
      {entries.length > 0 && <ul>{entries.map(([id, limit]) => <UsageLimit key={id} label={id} limit={limit} />)}</ul>}
      {!usage.rate_limits && entries.length === 0 && <p>Данные о лимитах не получены.</p>}
    </>}
  </section>
}
