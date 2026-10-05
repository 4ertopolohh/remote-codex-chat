import type { ConversationInfo } from '../../chat/useChat'
import { displayConversationTitle } from '../../localization'
import { ActionButton } from '../ActionButton/ActionButton'
import styles from './ConversationList.module.scss'

type Props = {
  conversations: ConversationInfo[]
  selectedId: string | null
  disabled: boolean
  onSelect: (id: string) => void
  onNew: () => void
}

export function ConversationList({ conversations, selectedId, disabled, onSelect, onNew }: Props) {
  return <nav className={styles.list} aria-label="История чатов">
    <ActionButton className={styles.newConversation} onClick={onNew} disabled={disabled}>Новый чат</ActionButton>
    <ul>
      {conversations.map(conversation => <li key={conversation.id}>
        <button type="button" disabled={disabled || conversation.id === selectedId} aria-current={conversation.id === selectedId ? 'page' : undefined} onClick={() => onSelect(conversation.id)}>
          {displayConversationTitle(conversation.title)}
        </button>
      </li>)}
    </ul>
  </nav>
}
