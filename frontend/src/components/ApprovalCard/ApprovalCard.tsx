import { useState } from 'react'
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
    {request.kind === 'command' && <><p>Command: <code>{request.details.command ?? 'Unavailable'}</code></p>{request.details.cwd && <p>Working directory: <code>{request.details.cwd}</code></p>}</>}
    {request.kind === 'file_change' && <p>File change request</p>}
    {request.details.reason && <p>Reason: {request.details.reason}</p>}
    {request.details.grantRoot && <p>Write root: <code>{request.details.grantRoot}</code></p>}
    {requiresUnknownFileAcknowledgement(request) && request.status === 'pending' && <label className={styles.acknowledge}><input type="checkbox" checked={acknowledged} disabled={!pending} onChange={event => setAcknowledged(event.target.checked)} /> Codex did not provide a list of changed files. I understand approval may allow file changes beyond the description shown here.</label>}
    {request.kind === 'user_input' && questions.map(question => <div className={styles.question} key={question.id}>
      <label htmlFor={`${request.id}-${question.id}`}>{question.header}: {question.question}</label>
      {question.options?.length ? <select id={`${request.id}-${question.id}`} value={answers[question.id] ?? ''} disabled={!pending} onChange={event => setAnswers(previous => ({ ...previous, [question.id]: event.target.value }))}>
        <option value="">Choose an answer</option>
        {question.options.map(option => <option key={option.label} value={option.label}>{option.label} — {option.description}</option>)}
        {question.is_other && <option value="__other__">Other</option>}
      </select> : <input id={`${request.id}-${question.id}`} type={question.is_secret ? 'password' : 'text'} value={answers[question.id] ?? ''} disabled={!pending} maxLength={10000} onChange={event => setAnswers(previous => ({ ...previous, [question.id]: event.target.value }))} />}
      {question.options?.length && question.is_other && answers[question.id] === '__other__' && <input aria-label={`${question.header} other answer`} type={question.is_secret ? 'password' : 'text'} value={otherAnswers[question.id] ?? ''} disabled={!pending} maxLength={10000} onChange={event => setOtherAnswers(previous => ({ ...previous, [question.id]: event.target.value }))} />}
    </div>)}
    {request.status !== 'pending' && <p role="status">{requestOutcomeText(request)}</p>}
    {submitting && request.status === 'pending' && <p role="status">Sending response…</p>}
    {request.kind === 'user_input' ? <button type="button" disabled={!pending || !inputAnswers} onClick={submitInput}>Send answer</button> : <div className={styles.actions}>
      <button type="button" disabled={!pending} onClick={() => { setSubmitting(true); onApproval(request.id, 'decline') }}>Decline</button>
      <button type="button" disabled={!pending || !canApprove(request, acknowledged)} onClick={() => { setSubmitting(true); onApproval(request.id, 'accept') }}>Approve</button>
    </div>}
  </section>
}
