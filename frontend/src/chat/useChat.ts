import { useEffect, useRef, useState } from 'react'

type Connection = 'connecting' | 'connected' | 'disconnected'
type Turn = 'idle' | 'running' | 'completed' | 'failed' | 'interrupted'
export type Message = { role: 'user' | 'assistant'; text: string }
export type ConversationInfo = { id: string; project_id: string; title: string; created_at: string; updated_at: string }
export type ModelCapability = { id: string; model: string; display_name: string; reasoning_efforts: string[]; default_reasoning_effort: string | null; is_default: boolean }
export type CollaborationCapability = { name: string; mode: string; model: string | null; reasoning_effort: string | null }

type ServerEvent =
  | { type: 'ready' }
  | { type: 'capabilities'; models: ModelCapability[]; collaboration_modes: CollaborationCapability[] }
  | { type: 'conversation_list'; conversations: ConversationInfo[] }
  | { type: 'conversation_selected'; conversation: ConversationInfo; messages: Message[] }
  | { type: 'turn_started' }
  | { type: 'steer_accepted'; text: string }
  | { type: 'assistant_delta'; text: string }
  | { type: 'agent_status'; status: string }
  | { type: 'turn_completed'; status: 'completed' | 'failed' | 'interrupted' }
  | { type: 'error'; code: string }

const savedConversationKey = 'remote-codex-chat.conversation-id'
const savedModelKey = 'remote-codex-chat.model-id'
const savedEffortKey = 'remote-codex-chat.reasoning-effort'

function isConversation(value: unknown): value is ConversationInfo {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return ['id', 'project_id', 'title', 'created_at', 'updated_at'].every(key => typeof item[key] === 'string')
}

function isMessage(value: unknown): value is Message {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return (item.role === 'user' || item.role === 'assistant') && typeof item.text === 'string'
}

function parseEvent(data: string): ServerEvent | null {
  try {
    const value: unknown = JSON.parse(data)
    if (!value || typeof value !== 'object' || !('type' in value)) return null
    const event = value as Record<string, unknown>
    if (event.type === 'ready' || event.type === 'turn_started') return event as ServerEvent
    if (event.type === 'capabilities' && Array.isArray(event.models) && event.models.every(isModel) && Array.isArray(event.collaboration_modes) && event.collaboration_modes.every(isMode)) return event as ServerEvent
    if (event.type === 'steer_accepted' && typeof event.text === 'string') return event as ServerEvent
    if (event.type === 'conversation_list' && Array.isArray(event.conversations) && event.conversations.every(isConversation)) return event as ServerEvent
    if (event.type === 'conversation_selected' && isConversation(event.conversation) && Array.isArray(event.messages) && event.messages.every(isMessage)) return event as ServerEvent
    if (event.type === 'assistant_delta' && typeof event.text === 'string') return event as ServerEvent
    if (event.type === 'agent_status' && typeof event.status === 'string') return event as ServerEvent
    if (event.type === 'turn_completed' && ['completed', 'failed', 'interrupted'].includes(String(event.status))) return event as ServerEvent
    if (event.type === 'error' && typeof event.code === 'string') return event as ServerEvent
  } catch { /* Ignore malformed server data. */ }
  return null
}

function isModel(value: unknown): value is ModelCapability {
  if (!value || typeof value !== 'object') return false
  const model = value as Record<string, unknown>
  return typeof model.id === 'string' && typeof model.model === 'string' && typeof model.display_name === 'string' && typeof model.is_default === 'boolean' && Array.isArray(model.reasoning_efforts) && model.reasoning_efforts.every(item => typeof item === 'string') && (model.default_reasoning_effort === null || typeof model.default_reasoning_effort === 'string')
}

function isMode(value: unknown): value is CollaborationCapability {
  if (!value || typeof value !== 'object') return false
  const mode = value as Record<string, unknown>
  return typeof mode.name === 'string' && typeof mode.mode === 'string' && (mode.model === null || typeof mode.model === 'string') && (mode.reasoning_effort === null || typeof mode.reasoning_effort === 'string')
}

export function useChat() {
  const socket = useRef<WebSocket | null>(null)
  const selectedIdRef = useRef<string | null>(null)
  const selectionPendingRef = useRef(false)
  const pendingPromptRef = useRef<string | null>(null)
  const [connection, setConnection] = useState<Connection>('connecting')
  const [turn, setTurn] = useState<Turn>('idle')
  const [agentStatus, setAgentStatus] = useState('idle')
  const [messages, setMessages] = useState<Message[]>([])
  const [conversations, setConversations] = useState<ConversationInfo[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selecting, setSelecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [models, setModels] = useState<ModelCapability[]>([])
  const [collaborationModes, setCollaborationModes] = useState<CollaborationCapability[]>([])
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null)
  const [selectedEffort, setSelectedEffort] = useState<string | null>(null)
  const [selectedMode, setSelectedMode] = useState<string | null>(null)
  const [stopPending, setStopPending] = useState(false)
  const [activeTurn, setActiveTurn] = useState(false)

  useEffect(() => {
    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    let disposed = false
    let retry: ReturnType<typeof setTimeout> | undefined
    function connect() {
      if (disposed) return
      setConnection('connecting')
      const ws = new WebSocket(`${scheme}//${window.location.host}/ws/chat`)
      socket.current = ws
      ws.onmessage = ({ data }: MessageEvent<string>) => {
        if (socket.current !== ws) return
        const event = parseEvent(data)
        if (!event) return
        switch (event.type) {
          case 'ready':
            setConnection('connected')
            setError(null)
            ws.send(JSON.stringify({ type: 'list_conversations' }))
            ws.send(JSON.stringify({ type: 'list_capabilities' }))
            break
          case 'capabilities': {
            setModels(event.models)
            setCollaborationModes(event.collaboration_modes)
            const previous = window.localStorage.getItem(savedModelKey)
            const selected = event.models.find(model => model.id === previous) ?? event.models.find(model => model.is_default) ?? event.models[0]
            if (selected) {
              setSelectedModelId(selected.id)
              window.localStorage.setItem(savedModelKey, selected.id)
              const savedEffort = window.localStorage.getItem(savedEffortKey)
              const effort = selected.id === previous && savedEffort && selected.reasoning_efforts.includes(savedEffort) ? savedEffort : selected.default_reasoning_effort ?? selected.reasoning_efforts[0] ?? null
              setSelectedEffort(effort)
              if (effort) window.localStorage.setItem(savedEffortKey, effort)
              else window.localStorage.removeItem(savedEffortKey)
            } else {
              setSelectedModelId(null)
              setSelectedEffort(null)
              window.localStorage.removeItem(savedModelKey)
              window.localStorage.removeItem(savedEffortKey)
            }
            setSelectedMode(previous => event.collaboration_modes.some(mode => mode.mode === previous) ? previous : null)
            break
          }
          case 'conversation_list': {
            setConversations(event.conversations)
            if (selectedIdRef.current === null && !selectionPendingRef.current) {
              const saved = window.localStorage.getItem(savedConversationKey)
              const choice = event.conversations.find(item => item.id === saved) ?? event.conversations[0]
              selectionPendingRef.current = true
              setSelecting(true)
              ws.send(JSON.stringify(choice ? { type: 'select_conversation', id: choice.id } : { type: 'new_conversation' }))
            }
            break
          }
          case 'conversation_selected':
            selectedIdRef.current = event.conversation.id
            setSelectedId(event.conversation.id)
            window.localStorage.setItem(savedConversationKey, event.conversation.id)
            selectionPendingRef.current = false
            setSelecting(false)
            setMessages(event.messages)
            setTurn('idle')
            setAgentStatus('idle')
            setError(null)
            ws.send(JSON.stringify({ type: 'list_conversations' }))
            break
          case 'turn_started': pendingPromptRef.current = null; setTurn('running'); setActiveTurn(true); setStopPending(false); setAgentStatus('starting'); break
          case 'steer_accepted': setMessages(previous => [...previous, { role: 'user', text: event.text }]); break
          case 'assistant_delta':
            setMessages(previous => {
              const last = previous.at(-1)
              if (last?.role === 'assistant') return [...previous.slice(0, -1), { role: 'assistant', text: last.text + event.text }]
              return [...previous, { role: 'assistant', text: event.text }]
            })
            break
          case 'agent_status': setAgentStatus(event.status); break
          case 'turn_completed': setTurn(event.status); setActiveTurn(false); setStopPending(false); setAgentStatus(event.status); break
          case 'error': {
            setError(event.code)
            if (pendingPromptRef.current !== null) {
              const pending = pendingPromptRef.current
              pendingPromptRef.current = null
              setMessages(previous => previous.at(-1)?.role === 'user' && previous.at(-1)?.text === pending ? previous.slice(0, -1) : previous)
              setTurn('idle')
              setActiveTurn(false)
            }
            const wasSelecting = selectionPendingRef.current
            selectionPendingRef.current = false
            setSelecting(false)
            if (wasSelecting || event.code === 'thread_unavailable' || event.code === 'conversation_not_found') {
              selectedIdRef.current = null
              setSelectedId(null)
              setMessages([])
              window.localStorage.removeItem(savedConversationKey)
            }
            if (!['invalid_message', 'turn_in_progress', 'no_active_turn', 'steer_failed', 'model_unavailable', 'reasoning_unavailable', 'collaboration_unavailable'].includes(event.code)) setTurn('failed')
            break
          }
        }
      }
      ws.onclose = () => {
        if (disposed || socket.current !== ws) return
        setConnection('disconnected')
        setModels([])
        setCollaborationModes([])
        setStopPending(false)
        setActiveTurn(false)
        setTurn(current => current === 'running' ? 'failed' : current)
        selectionPendingRef.current = false
        setSelecting(false)
        selectedIdRef.current = null
        setSelectedId(null)
        retry = setTimeout(connect, 500)
      }
      ws.onerror = () => { if (socket.current === ws) setError('connection_failed') }
    }
    connect()
    return () => {
      disposed = true
      clearTimeout(retry)
      socket.current?.close()
      socket.current = null
    }
  }, [])

  function send(text: string): boolean {
    if (socket.current?.readyState !== WebSocket.OPEN || connection !== 'connected' || !selectedId || selectionPendingRef.current || turn === 'running' || !text.trim()) return false
    const command: Record<string, string> = { type: 'submit_prompt', text }
    if (selectedModelId) command.model_id = selectedModelId
    if (selectedEffort) command.reasoning_effort = selectedEffort
    if (selectedMode) command.collaboration_mode = selectedMode
    socket.current.send(JSON.stringify(command))
    pendingPromptRef.current = text
    setMessages(previous => [...previous, { role: 'user', text }])
    setTurn('running')
    setActiveTurn(false)
    setError(null)
    return true
  }

  function selectModel(id: string): void {
    const model = models.find(item => item.id === id)
    if (!model || turn === 'running') return
    setSelectedModelId(id)
    window.localStorage.setItem(savedModelKey, id)
    const effort = model.default_reasoning_effort ?? model.reasoning_efforts[0] ?? null
    setSelectedEffort(effort)
    if (effort) window.localStorage.setItem(savedEffortKey, effort)
    else window.localStorage.removeItem(savedEffortKey)
  }

  function selectEffort(effort: string): void {
    const model = models.find(item => item.id === selectedModelId)
    if (!model?.reasoning_efforts.includes(effort) || turn === 'running') return
    setSelectedEffort(effort)
    window.localStorage.setItem(savedEffortKey, effort)
  }

  function selectMode(mode: string | null): void {
    if (turn === 'running' || (mode && !collaborationModes.some(item => item.mode === mode))) return
    setSelectedMode(mode)
  }

  function refreshCapabilities(): void {
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type: 'list_capabilities' }))
  }

  function stop(): void {
    if (socket.current?.readyState !== WebSocket.OPEN || turn !== 'running' || !activeTurn || stopPending) return
    setStopPending(true)
    socket.current.send(JSON.stringify({ type: 'stop_turn' }))
  }

  function steer(text: string): boolean {
    if (socket.current?.readyState !== WebSocket.OPEN || turn !== 'running' || !activeTurn || stopPending || !text.trim()) return false
    socket.current.send(JSON.stringify({ type: 'steer_turn', text }))
    setError(null)
    return true
  }

  function newConversation(): void {
    if (socket.current?.readyState !== WebSocket.OPEN || turn === 'running' || selectionPendingRef.current) return
    selectionPendingRef.current = true
    setSelecting(true)
    socket.current.send(JSON.stringify({ type: 'new_conversation' }))
  }

  function selectConversation(id: string): void {
    if (socket.current?.readyState !== WebSocket.OPEN || turn === 'running' || selectionPendingRef.current || id === selectedId) return
    selectionPendingRef.current = true
    setSelecting(true)
    socket.current.send(JSON.stringify({ type: 'select_conversation', id }))
  }

  return { connection, turn, activeTurn, agentStatus, messages, conversations, selectedId, selecting, error, models, collaborationModes, selectedModelId, selectedEffort, selectedMode, stopPending, send, steer, stop, selectModel, selectEffort, selectMode, refreshCapabilities, newConversation, selectConversation }
}
