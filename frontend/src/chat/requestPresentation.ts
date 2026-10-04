import type { InputQuestion, PendingRequest } from './useChat'

export function requestTitle(request: PendingRequest): string {
  if (request.status !== 'pending') return `Request ${request.status}`
  return request.kind === 'user_input' ? 'User input required' : 'Approval required'
}

export function requestOutcomeText(request: PendingRequest): string | null {
  if (request.status === 'completed') return 'Response sent.'
  if (request.status === 'expired') return request.kind === 'user_input' ? 'Timed out without an answer.' : 'Timed out; approval was declined.'
  if (request.status === 'cancelled') return request.kind === 'user_input' ? 'Cancelled without an answer.' : 'Cancelled; approval was declined.'
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
