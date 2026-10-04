import { useState, type FormEvent } from 'react'
import styles from './MessageInput.module.scss'

export function MessageInput({ onSend, disabled }: { onSend: (text: string) => boolean; disabled: boolean }) {
  const [text, setText] = useState('')
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (onSend(text.trim())) setText('')
  }
  return <form className={styles.input} onSubmit={submit}>
    <label htmlFor="prompt">Message</label>
    <textarea id="prompt" value={text} onChange={event => setText(event.target.value)} rows={3} maxLength={10000} disabled={disabled} />
    <button type="submit" disabled={disabled || !text.trim()}>Send</button>
  </form>
}
