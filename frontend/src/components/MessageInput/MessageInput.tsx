import { useRef, useState, type FormEvent } from 'react'
import styles from './MessageInput.module.scss'

export function MessageInput({ onSend, onSteer, onStop, running, activeTurn, stopPending, disabled }: { onSend: (text: string) => boolean; onSteer: (text: string) => boolean; onStop: () => void; running: boolean; activeTurn: boolean; stopPending: boolean; disabled: boolean }) {
  const [text, setText] = useState('')
  const textarea = useRef<HTMLTextAreaElement>(null)
  function resize() {
    const element = textarea.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 192)}px`
    element.style.overflowY = element.scrollHeight > 192 ? 'auto' : 'hidden'
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if ((running ? onSteer : onSend)(text.trim())) {
      setText('')
      requestAnimationFrame(resize)
    }
  }
  return <form className={styles.input} onSubmit={submit}>
    <label htmlFor="prompt">Message</label>
    <textarea ref={textarea} id="prompt" value={text} onChange={event => { setText(event.target.value); resize() }} rows={2} maxLength={10000} disabled={disabled} />
    <div className={styles.actions}>
      {running && <button type="button" onClick={onStop} disabled={disabled || !activeTurn || stopPending}>Stop</button>}
      <button type="submit" disabled={disabled || (running && (!activeTurn || stopPending)) || !text.trim()}>{running ? 'Steer active turn' : 'Send'}</button>
    </div>
  </form>
}
