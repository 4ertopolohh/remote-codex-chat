import { useState } from 'react'
import { ActionButton } from '../ActionButton/ActionButton'
import type { PendingRequest } from '../../chat/useChat'
import { buildUserInputAnswers, canApprove, requestOutcomeText, requestTitle, requiresUnknownFileAcknowledgement } from '../../chat/requestPresentation'
import styles from './ApprovalCard.module.scss'

export function ApprovalCard({ request, onApproval, onInput }: { request: PendingRequest; onApproval: (id: string, decision: 'accept' | 'decline') => void; onInput: (id: string, answers: Record<string, string[]>) => void }) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [otherAnswers, setOtherAnswers] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [acknowledged, setAcknowledged] = useState(false)
  const pending = request.status === 'pending' && !submitting
  const questions = request.details.questions ?? []
  const title = requestTitle(request)
  const inputAnswers = buildUserInputAnswers(questions, answers, otherAnswers)

  function submitInput() {
    if (!pending || !inputAnswers) return
    setSubmitting(true)
    onInput(request.id, inputAnswers)
  }

  return <section className={styles.card} aria-label={title}>
    <h2>{title}</h2>
    {request.kind === 'command' && <p>Команда: <code>{request.details.command ?? 'Недоступна'}</code></p>}
    {request.kind === 'file_change' && <p>Запрос на изменение файлов</p>}
    {request.details.reason && <p>Причина: {request.details.reason}</p>}
    {requiresUnknownFileAcknowledgement(request) && request.status === 'pending' && <label className={styles.acknowledge}><input type="checkbox" checked={acknowledged} disabled={!pending} onChange={event => setAcknowledged(event.target.checked)} /> Codex не указал список изменённых файлов. Я понимаю, что после одобрения могут измениться файлы, не описанные в запросе.</label>}
    {request.kind === 'user_input' && questions.map(question => <div className={styles.question} key={question.id}>
      <label htmlFor={`${request.id}-${question.id}`}>{question.header}: {question.question}</label>
      {question.options?.length ? <select id={`${request.id}-${question.id}`} value={answers[question.id] ?? ''} disabled={!pending} onChange={event => setAnswers(previous => ({ ...previous, [question.id]: event.target.value }))}>
        <option value="">Выберите ответ</option>
        {question.options.map(option => <option key={option.label} value={option.label}>{option.label} — {option.description}</option>)}
        {question.is_other && <option value="__other__">Другой ответ</option>}
      </select> : <input id={`${request.id}-${question.id}`} type={question.is_secret ? 'password' : 'text'} value={answers[question.id] ?? ''} disabled={!pending} maxLength={10000} onChange={event => setAnswers(previous => ({ ...previous, [question.id]: event.target.value }))} />}
      {question.options?.length && question.is_other && answers[question.id] === '__other__' && <input aria-label={`${question.header}: свой ответ`} type={question.is_secret ? 'password' : 'text'} value={otherAnswers[question.id] ?? ''} disabled={!pending} maxLength={10000} onChange={event => setOtherAnswers(previous => ({ ...previous, [question.id]: event.target.value }))} />}
    </div>)}
    {request.status !== 'pending' && <p role="status">{requestOutcomeText(request)}</p>}
    {submitting && request.status === 'pending' && <p role="status">Отправляем ответ…</p>}
    {request.kind === 'user_input' ? <ActionButton disabled={!pending || !inputAnswers} onClick={submitInput}>Отправить ответ</ActionButton> : <div className={styles.actions}>
      <ActionButton tone="secondary" disabled={!pending} onClick={() => { setSubmitting(true); onApproval(request.id, 'decline') }}>Отклонить</ActionButton>
      <ActionButton disabled={!pending || !canApprove(request, acknowledged)} onClick={() => { setSubmitting(true); onApproval(request.id, 'accept') }}>Одобрить</ActionButton>
    </div>}
  </section>
}
