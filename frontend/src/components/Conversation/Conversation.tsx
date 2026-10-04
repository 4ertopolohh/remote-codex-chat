import { useLayoutEffect, useRef } from 'react'
import type { Message } from '../../chat/useChat'
import styles from './Conversation.module.scss'
import narrow from './Conversation480.module.scss'

function renderMessageText(text: string) {
  return <div className={styles.text}>{text.split(/(```[\s\S]*?(?:```|$))/g).map((part, index) => {
    if (part.startsWith('```')) {
      const body = part.slice(3, part.endsWith('```') ? -3 : undefined).replace(/^[^\n]*(?:\n|$)/, '')
      return <pre key={index}><code>{body}</code></pre>
    }
    return part ? <p key={index}>{part}</p> : null
  })}</div>
}

export function Conversation({ messages, loading = false, conversationId = null }: { messages: Message[]; loading?: boolean; conversationId?: string | null }) {
  const viewport = useRef<HTMLElement>(null)
  const following = useRef(true)
  const previousId = useRef(conversationId)

  useLayoutEffect(() => {
    if (previousId.current !== conversationId) {
      following.current = true
      previousId.current = conversationId
    }
    const element = viewport.current
    if (element && following.current) element.scrollTop = element.scrollHeight - element.clientHeight
  }, [conversationId, messages])

  function onScroll() {
    const element = viewport.current
    if (element) following.current = element.scrollHeight - element.clientHeight - element.scrollTop < 72
  }

  return <section ref={viewport} className={`${styles.conversation} ${narrow.conversation}`} aria-label="Conversation" role="region" onScroll={onScroll}>
    {messages.length === 0 && <div className={styles.empty}>
      <span className={styles.emptyMark}>✳</span>
      <h2>{loading ? 'Opening conversation…' : 'Start a conversation'}</h2>
      <p>{loading ? 'Your messages will appear here.' : 'Ask Codex about your selected project.'}</p>
    </div>}
    {messages.map((message, index) => <article key={index} className={`${styles.message} ${narrow.message} ${message.role === 'user' ? styles.user : styles.assistant}`}>
      <strong>{message.role === 'user' ? 'You' : 'Codex'}</strong>
      {renderMessageText(message.text)}
    </article>)}
  </section>
}
