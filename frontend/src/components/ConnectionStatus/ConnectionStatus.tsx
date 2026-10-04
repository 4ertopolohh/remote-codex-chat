import styles from './ConnectionStatus.module.scss'

export function ConnectionStatus({ status }: { status: 'connecting' | 'connected' | 'disconnected' }) {
  return <span className={styles.status} role="status">Connection: {status}</span>
}
