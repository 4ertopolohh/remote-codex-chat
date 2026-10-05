import styles from './ConnectionStatus.module.scss'

export function ConnectionStatus({ status }: { status: 'connecting' | 'connected' | 'disconnected' | 'reconnecting' }) {
  return <span className={styles.status} data-status={status} role="status">{status === 'connected' ? 'На связи' : status === 'connecting' ? 'Подключаемся' : status === 'reconnecting' ? 'Переподключаемся' : 'Нет связи'}</span>
}
