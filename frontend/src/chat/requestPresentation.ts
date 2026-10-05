import type { InputQuestion, PendingRequest } from './useChat'

export function requestTitle(request: PendingRequest): string {
  if (request.status !== 'pending') return `Запрос: ${({ completed: 'выполнен', expired: 'истёк', cancelled: 'отменён', unknown: 'результат неизвестен' } as Record<string, string>)[request.status] ?? 'статус неизвестен'}`
  return request.kind === 'user_input' ? 'Нужен ваш ответ' : 'Требуется одобрение'
}

export function requestOutcomeText(request: PendingRequest): string | null {
  if (request.status === 'unknown') return 'Связь прервалась, и результат запроса неизвестен. Проверьте переписку, прежде чем продолжить.'
  if (request.status === 'completed') return 'Ответ отправлен.'
  if (request.status === 'expired') return request.kind === 'user_input' ? 'Время ожидания ответа истекло.' : 'Время ожидания истекло, запрос отклонён.'
  if (request.status === 'cancelled') return request.kind === 'user_input' ? 'Запрос отменён без ответа.' : 'Запрос отменён и отклонён.'
  return null
}

export function requiresUnknownFileAcknowledgement(request: PendingRequest): boolean {
  return request.kind === 'file_change'
}

export function canApprove(request: PendingRequest, acknowledged: boolean): boolean {
  if (request.status !== 'pending') return false
  if (request.kind === 'command') return Boolean(request.details.command)
  if (request.kind === 'file_change') return !requiresUnknownFileAcknowledgement(request) || acknowledged
  return false
}

export function buildUserInputAnswers(questions: InputQuestion[], selected: Record<string, string>, other: Record<string, string>): Record<string, string[]> | null {
  if (questions.length === 0) return null
  const answers: Record<string, string[]> = {}
  for (const question of questions) {
    const choice = selected[question.id]
    const value = (choice === '__other__' ? other[question.id] : choice)?.trim()
    if (!value) return null
    answers[question.id] = [value]
  }
  return answers
}
