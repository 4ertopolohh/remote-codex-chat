import type { Usage, UsageLimit, UsageWindow } from '../../chat/useChat'
import styles from './UsagePanel.module.scss'

type Props = { usage: Usage | null; onRefresh: () => void; connected: boolean }

function Window({ title, window }: { title: string; window: UsageWindow }) {
  return <div className={styles.window}>
    <span>{title}</span>
    {window.used_percent !== undefined && <strong>{window.used_percent}% used</strong>}
    {window.window_duration_mins !== undefined && <span>{window.window_duration_mins} min window</span>}
    {window.resets_at !== undefined && <span>Resets {new Date(window.resets_at * 1000).toLocaleString()}</span>}
  </div>
}

function Limit({ label, limit }: { label: string; limit: UsageLimit }) {
  return <li className={styles.limit}>
    <strong>{limit.limit_name ?? label}</strong>
    {limit.primary && <Window title="Primary" window={limit.primary} />}
    {limit.secondary && <Window title="Secondary" window={limit.secondary} />}
    {!limit.primary && !limit.secondary && <span>Window details unavailable</span>}
  </li>
}

export function UsagePanel({ usage, onRefresh, connected }: Props) {
  const entries = usage ? Object.entries(usage.rate_limits_by_id) : []
  return <section className={styles.panel} aria-label="Usage and rate limits">
    <div className={styles.heading}><h2>Usage</h2><button type="button" onClick={onRefresh} disabled={!connected}>Refresh</button></div>
    {!usage && <p>Loading usage…</p>}
    {usage?.status === 'unsupported' && <p>Usage information is not supported by this Codex runtime.</p>}
    {usage?.status === 'error' && <p>Usage information is unavailable</p>}
    {usage?.status === 'available' && <>
      {usage.ordinary_usage_allowed !== null && <p>{usage.ordinary_usage_allowed ? 'Ordinary usage allowed' : 'Ordinary usage unavailable'}</p>}
      {usage.rate_limits && (entries.length === 0 || !usage.rate_limits.limit_id || !usage.rate_limits_by_id[usage.rate_limits.limit_id]) && <ul><Limit label="Account limits" limit={usage.rate_limits} /></ul>}
      {entries.length > 0 && <ul>{entries.map(([id, limit]) => <Limit key={id} label={id} limit={limit} />)}</ul>}
      {!usage.rate_limits && entries.length === 0 && <p>No limit details were returned.</p>}
    </>}
  </section>
}
