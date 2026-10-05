import type { Usage } from '../../chat/useChat'
import { ActionButton } from '../ActionButton/ActionButton'
import { UsageLimit } from '../UsageLimit/UsageLimit'
import styles from './UsagePanel.module.scss'

type Props = { usage: Usage | null; onRefresh: () => void; connected: boolean }

export function UsagePanel({ usage, onRefresh, connected }: Props) {
  const entries = usage ? Object.entries(usage.rate_limits_by_id) : []
  return <section className={styles.panel} aria-label="Usage and rate limits">
    <div className={styles.heading}><h2>Usage</h2><ActionButton tone="secondary" onClick={onRefresh} disabled={!connected}>Refresh</ActionButton></div>
    {!usage && <p>Loading usage…</p>}
    {usage?.status === 'unsupported' && <p>Usage information is not supported by this Codex runtime.</p>}
    {usage?.status === 'error' && <p>Usage information is unavailable</p>}
    {usage?.status === 'available' && <>
      {usage.ordinary_usage_allowed !== null && <p>{usage.ordinary_usage_allowed ? 'Ordinary usage allowed' : 'Ordinary usage unavailable'}</p>}
      {usage.rate_limits && (entries.length === 0 || !usage.rate_limits.limit_id || !usage.rate_limits_by_id[usage.rate_limits.limit_id]) && <ul><UsageLimit label="Account limits" limit={usage.rate_limits} /></ul>}
      {entries.length > 0 && <ul>{entries.map(([id, limit]) => <UsageLimit key={id} label={id} limit={limit} />)}</ul>}
      {!usage.rate_limits && entries.length === 0 && <p>No limit details were returned.</p>}
    </>}
  </section>
}
