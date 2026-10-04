import styles from './ConnectionStatus.module.scss'

export function ConnectionStatus({ status }: { status: 'connecting' | 'connected' | 'disconnected' }) {
  return <span className={styles.status} data-status={status} role="status">{status === 'connected' ? 'Online' : status === 'connecting' ? 'Connecting' : 'Offline'}</span>
}
