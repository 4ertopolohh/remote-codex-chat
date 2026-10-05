import styles from './TurnStatus.module.scss'

const recovery: Record<string, string> = {
  codex_unavailable: 'Codex is unavailable on the PC. Restart the backend after checking Codex.',
  codex_failure: 'Codex stopped responding. Check the backend and review conversation history before continuing.',
  thread_unavailable: 'This Codex thread cannot be resumed. Start a new conversation.',
  conversation_not_found: 'This conversation is no longer available. Start a new conversation.',
  model_unavailable: 'The selected model is unavailable. Choose a listed model and send again.',
  reasoning_unavailable: 'The selected reasoning level is unavailable. Choose a listed level and send again.',
  collaboration_unavailable: 'The selected mode is unavailable. Choose a listed mode and send again.',
  duplicate_submission: 'This prompt was already submitted. Review conversation history before sending another prompt.',
  connection_failed: 'Connection failed. Check the network or tunnel; reconnect will be attempted.',
}

export function TurnStatus({ turn, agentStatus, error }: { turn: string; agentStatus: string; error: string | null }) {
  return <div className={styles.status} role="status">
    <span>Turn: {turn}</span><span>Agent: {agentStatus}</span>{error && <span>{recovery[error] ?? `Error: ${error.replaceAll('_', ' ')}`}</span>}
  </div>
}
