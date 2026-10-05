import { useEffect, useRef, useState } from 'react'
import { useChat } from '../../chat/useChat'
import { useViewportDock } from '../../hooks/useViewportDock'
import { ConnectionStatus } from '../ConnectionStatus/ConnectionStatus'
import { ActionButton } from '../ActionButton/ActionButton'
import { ApprovalCard } from '../ApprovalCard/ApprovalCard'
import { Conversation } from '../Conversation/Conversation'
import { ConversationList } from '../ConversationList/ConversationList'
import { MessageInput } from '../MessageInput/MessageInput'
import { ModelSelector } from '../ModelSelector/ModelSelector'
import { ProjectSelector } from '../ProjectSelector/ProjectSelector'
import { TurnStatus } from '../TurnStatus/TurnStatus'
import { UsagePanel } from '../UsagePanel/UsagePanel'
import styles from './App.module.scss'
import responsive from './App768.module.scss'
import narrow from './App480.module.scss'
import short from './AppHeight480.module.scss'

export function App({ onLogout, onAuthRequired, authError }: { onLogout?: () => void; onAuthRequired?: () => void; authError?: string | null }) {
  const chat = useChat(onAuthRequired)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [isNarrow, setIsNarrow] = useState(() => window.matchMedia?.('(max-width: 768px)').matches ?? false)
  const historyTrigger = useRef<HTMLButtonElement>(null)
  const historyClose = useRef<HTMLButtonElement>(null)
  const historyPanel = useRef<HTMLElement>(null)
  const bottomDock = useViewportDock()
  const controlsDisabled = chat.connection !== 'connected' || chat.selecting || chat.turn === 'running'
  const current = chat.conversations.find(item => item.id === chat.selectedId)

  useEffect(() => {
    const media = window.matchMedia?.('(max-width: 768px)')
    if (!media) return
    const update = () => setIsNarrow(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    if (!historyOpen) return
    if (isNarrow) historyClose.current?.focus()
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setHistoryOpen(false)
        historyTrigger.current?.focus()
      }
      if (event.key === 'Tab' && isNarrow && historyPanel.current) {
        const panel = historyPanel.current
        const focusable = [...panel.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])')]
        const first = focusable[0]
        const last = focusable.at(-1)
        if (!first || !last) return
        if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) {
          event.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onEscape)
    return () => document.removeEventListener('keydown', onEscape)
  }, [historyOpen, isNarrow])

  function closeHistory() {
    setHistoryOpen(false)
    historyTrigger.current?.focus()
  }

  function selectConversation(id: string) {
    chat.selectConversation(id)
    closeHistory()
  }

  function newConversation() {
    chat.newConversation()
    closeHistory()
  }

  return <main className={`${styles.app} ${responsive.app} ${narrow.app}`}>
    <header className={`${styles.header} ${responsive.header}`}>
      <div className={`${styles.brand} ${responsive.brand}`}><span className={`${styles.brandMark} ${narrow.brandMark}`} aria-hidden="true">✳</span><div><strong>Codex</strong><small>Remote workspace</small></div></div>
      <div className={`${styles.headerActions} ${responsive.headerActions}`}>
        <ConnectionStatus status={chat.connection} />
        {onLogout && <ActionButton tone="secondary" onClick={onLogout}>Sign out</ActionButton>}
        <button ref={historyTrigger} className={`${styles.historyToggle} ${responsive.historyToggle}`} type="button" aria-expanded={historyOpen} aria-controls="conversation-history" onClick={() => setHistoryOpen(value => !value)}>History</button>
      </div>
    </header>

    <aside ref={historyPanel} id="conversation-history" className={`${styles.sidebar} ${responsive.sidebar} ${historyOpen ? responsive.sidebarOpen : ''}`} inert={isNarrow && !historyOpen} aria-hidden={isNarrow && !historyOpen} role={isNarrow && historyOpen ? 'dialog' : undefined} aria-modal={isNarrow && historyOpen ? true : undefined} aria-label={isNarrow && historyOpen ? 'Conversation history' : undefined}>
      <div className={styles.sidebarHeading}><span>Workspace</span><button ref={historyClose} className={`${styles.closeHistory} ${responsive.closeHistory}`} type="button" onClick={closeHistory} aria-label="Close history">×</button></div>
      <ProjectSelector projects={chat.projects} selectedId={chat.selectedProjectId} disabled={controlsDisabled} onSelect={chat.selectProject} />
      <ConversationList conversations={chat.conversations} selectedId={chat.selectedId} disabled={controlsDisabled} onSelect={selectConversation} onNew={newConversation} />
      <UsagePanel usage={chat.usage} connected={chat.connection === 'connected'} onRefresh={chat.refreshUsage} />
    </aside>
    {historyOpen && <button className={`${styles.backdrop} ${responsive.backdrop}`} type="button" tabIndex={-1} aria-hidden="true" onClick={closeHistory} />}

    <section className={`${styles.workspace} ${responsive.workspace}`} aria-label="Chat workspace" inert={isNarrow && historyOpen} aria-hidden={isNarrow && historyOpen}>
      <div className={`${styles.conversationHeader} ${narrow.conversationHeader}`}>
        <div className={`${styles.conversationTitle} ${narrow.conversationTitle}`}><span className={styles.eyebrow}>CONVERSATION</span><h1>{chat.selecting ? 'Opening conversation…' : current?.title ?? 'New conversation'}</h1></div>
        <span className={`${styles.projectName} ${narrow.projectName}`}>{chat.projects.find(item => item.id === chat.selectedProjectId)?.name ?? 'No project'}</span>
      </div>
      {authError && <div className={styles.connectionNotice} role="alert">{authError}</div>}
      {chat.connection !== 'connected' && <div className={styles.connectionNotice} role="status">{chat.connection === 'connecting' ? 'Connecting to Codex…' : chat.connection === 'reconnecting' ? 'Reconnecting to Codex…' : 'Connection lost. Reconnecting…'}</div>}
      {chat.turn === 'unknown' && <div className={styles.connectionNotice} role="alert">The previous turn's outcome is unknown. Review the conversation before continuing. The prompt will not be sent again automatically. {chat.connection === 'connected' && chat.selectedId && <button type="button" onClick={chat.acknowledgeUnknown}>I reviewed the conversation</button>}</div>}
      <Conversation conversationId={chat.selectedId} messages={chat.selecting ? [] : chat.messages} loading={chat.selecting} />
      <div ref={bottomDock} className={`${styles.bottomDock} ${narrow.bottomDock} ${short.bottomDock}`}>
        {chat.requests.length > 0 && <div className={styles.requests} aria-label="Requests needing attention">{chat.requests.map(request => <ApprovalCard key={request.id} request={request} onApproval={chat.answerApproval} onInput={chat.answerUserInput} />)}</div>}
        <TurnStatus turn={chat.turn} agentStatus={chat.agentStatus} error={chat.error} />
        <ModelSelector models={chat.models} collaborationModes={chat.collaborationModes} modelId={chat.selectedModelId} effort={chat.selectedEffort} mode={chat.selectedMode} disabled={controlsDisabled} onModel={chat.selectModel} onEffort={chat.selectEffort} onMode={chat.selectMode} onRefresh={chat.refreshCapabilities} />
        <MessageInput onSend={chat.send} onSteer={chat.steer} onStop={chat.stop} running={chat.turn === 'running'} activeTurn={chat.activeTurn} stopPending={chat.stopPending} disabled={chat.connection !== 'connected' || !chat.selectedId || chat.selecting || chat.turn === 'unknown'} />
      </div>
    </section>
  </main>
}
