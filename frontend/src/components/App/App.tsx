import { useChat } from '../../chat/useChat'
import { ConnectionStatus } from '../ConnectionStatus/ConnectionStatus'
import { Conversation } from '../Conversation/Conversation'
import { ConversationList } from '../ConversationList/ConversationList'
import { MessageInput } from '../MessageInput/MessageInput'
import { TurnStatus } from '../TurnStatus/TurnStatus'
import styles from './App.module.scss'

export function App() {
  const chat = useChat()
  return <main className={styles.app}>
    <header><h1>Remote Codex Chat</h1><ConnectionStatus status={chat.connection} /></header>
    <ConversationList conversations={chat.conversations} selectedId={chat.selectedId} disabled={chat.connection !== 'connected' || chat.selecting || chat.turn === 'running'} onSelect={chat.selectConversation} onNew={chat.newConversation} />
    <Conversation messages={chat.messages} />
    <TurnStatus turn={chat.turn} agentStatus={chat.agentStatus} error={chat.error} />
    <MessageInput onSend={chat.send} disabled={chat.connection !== 'connected' || !chat.selectedId || chat.selecting || chat.turn === 'running'} />
  </main>
}
