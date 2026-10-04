import styles from './TurnStatus.module.scss'

export function TurnStatus({ turn, agentStatus, error }: { turn: string; agentStatus: string; error: string | null }) {
  return <div className={styles.status} role="status">
    <span>Turn: {turn}</span><span>Agent: {agentStatus}</span>{error && <span>Error: {error.replaceAll('_', ' ')}</span>}
  </div>
}
