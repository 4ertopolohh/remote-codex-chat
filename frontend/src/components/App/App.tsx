import { useChat } from '../../chat/useChat'
import { ConnectionStatus } from '../ConnectionStatus/ConnectionStatus'
import { ApprovalCard } from '../ApprovalCard/ApprovalCard'
import { Conversation } from '../Conversation/Conversation'
import { ConversationList } from '../ConversationList/ConversationList'
import { MessageInput } from '../MessageInput/MessageInput'
import { ModelSelector } from '../ModelSelector/ModelSelector'
import { ProjectSelector } from '../ProjectSelector/ProjectSelector'
import { TurnStatus } from '../TurnStatus/TurnStatus'
import styles from './App.module.scss'

export function App() {
  const chat = useChat()
  return <main className={styles.app}>
    <header><h1>Remote Codex Chat</h1><ConnectionStatus status={chat.connection} /></header>
    <ProjectSelector projects={chat.projects} selectedId={chat.selectedProjectId} disabled={chat.connection !== 'connected' || chat.selecting || chat.turn === 'running'} onSelect={chat.selectProject} />
    <ConversationList conversations={chat.conversations} selectedId={chat.selectedId} disabled={chat.connection !== 'connected' || chat.selecting || chat.turn === 'running'} onSelect={chat.selectConversation} onNew={chat.newConversation} />
    <Conversation messages={chat.messages} />
    {chat.requests.map(request => <ApprovalCard key={request.id} request={request} onApproval={chat.answerApproval} onInput={chat.answerUserInput} />)}
    <TurnStatus turn={chat.turn} agentStatus={chat.agentStatus} error={chat.error} />
    <ModelSelector models={chat.models} collaborationModes={chat.collaborationModes} modelId={chat.selectedModelId} effort={chat.selectedEffort} mode={chat.selectedMode} disabled={chat.connection !== 'connected' || chat.selecting || chat.turn === 'running'} onModel={chat.selectModel} onEffort={chat.selectEffort} onMode={chat.selectMode} onRefresh={chat.refreshCapabilities} />
    <MessageInput onSend={chat.send} onSteer={chat.steer} onStop={chat.stop} running={chat.turn === 'running'} activeTurn={chat.activeTurn} stopPending={chat.stopPending} disabled={chat.connection !== 'connected' || !chat.selectedId || chat.selecting} />
  </main>
}
