import styles from './TurnStatus.module.scss'

const recovery: Record<string, string> = {
  invalid_message: 'Не удалось обработать запрос. Проверьте текст и попробуйте снова.',
  project_not_found: 'Выбранный проект недоступен. Выберите другой проект.',
  project_unavailable: 'Не удалось открыть проект. Проверьте настройки и повторите попытку.',
  no_active_turn: 'Сейчас нет активного ответа, который можно остановить или направить.',
  request_unavailable: 'Запрос Codex больше недоступен. Проверьте переписку, прежде чем продолжить.',
  stop_failed: 'Не удалось остановить ответ. Попробуйте ещё раз.',
  steer_failed: 'Не удалось направить текущий ответ. Попробуйте отправить сообщение ещё раз.',
  turn_in_progress: 'Уже выполняется другой запрос. Дождитесь его завершения или остановите его.',
  codex_unavailable: 'Codex недоступен на компьютере. Проверьте Codex и перезапустите backend.',
  codex_failure: 'Codex перестал отвечать. Проверьте backend и историю чата, прежде чем продолжить.',
  thread_unavailable: 'Не удалось восстановить переписку Codex. Начните новый чат.',
  conversation_not_found: 'Этот чат больше недоступен. Начните новый чат.',
  model_unavailable: 'Выбранная модель недоступна. Выберите модель из списка и отправьте запрос снова.',
  reasoning_unavailable: 'Выбранный уровень рассуждений недоступен. Выберите другой уровень и отправьте запрос снова.',
  collaboration_unavailable: 'Выбранный режим недоступен. Выберите другой режим и отправьте запрос снова.',
  duplicate_submission: 'Этот запрос уже отправлен. Проверьте историю чата, прежде чем отправлять следующий.',
  connection_failed: 'Не удалось подключиться. Проверьте сеть или туннель; приложение попробует подключиться снова.',
}

const turnLabels: Record<string, string> = { idle: 'ожидает', running: 'выполняется', completed: 'завершён', failed: 'ошибка', interrupted: 'прерван', unknown: 'результат неизвестен' }
const agentLabels: Record<string, string> = { idle: 'ожидает', starting: 'запускается', running: 'работает', stopping: 'останавливается', completed: 'завершил работу', failed: 'ошибка', interrupted: 'прерван', unknown: 'состояние неизвестно' }

export function TurnStatus({ turn, agentStatus, error }: { turn: string; agentStatus: string; error: string | null }) {
  return <div className={styles.status} role="status">
    <span>Запрос: {turnLabels[turn] ?? 'состояние неизвестно'}</span><span>Агент: {agentLabels[agentStatus] ?? 'состояние неизвестно'}</span>{error && <span>{recovery[error] ?? 'Не удалось выполнить действие. Проверьте подключение и попробуйте ещё раз.'}</span>}
  </div>
}
