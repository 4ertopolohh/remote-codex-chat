import type { Message } from '../../chat/useChat'
import styles from './Conversation.module.scss'

export function Conversation({ messages }: { messages: Message[] }) {
  return <section className={styles.conversation} aria-label="Conversation" aria-live="polite">
    {messages.length === 0 && <p>Send a prompt to start.</p>}
    {messages.map((message, index) => <article key={index} className={styles.message}>
      <strong>{message.role === 'user' ? 'You' : 'Codex'}</strong>
      <p>{message.text}</p>
    </article>)}
  </section>
}
