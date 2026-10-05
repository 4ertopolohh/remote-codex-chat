import { useEffect, useRef, useState } from 'react'

type Connection = 'connecting' | 'connected' | 'disconnected' | 'reconnecting'
type Turn = 'idle' | 'running' | 'completed' | 'failed' | 'interrupted'
export type Message = { role: 'user' | 'assistant'; text: string }
export type ConversationInfo = { id: string; project_id: string; title: string; created_at: string; updated_at: string }
export type ProjectInfo = { id: string; name: string }
export type ModelCapability = { id: string; model: string; display_name: string; reasoning_efforts: string[]; default_reasoning_effort: string | null; is_default: boolean }
export type CollaborationCapability = { name: string; mode: string; model: string | null; reasoning_effort: string | null }
export type InputQuestion = { id: string; header: string; question: string; options: { label: string; description: string }[] | null; is_other: boolean; is_secret: boolean }
export type PendingRequest = { id: string; kind: 'command' | 'file_change' | 'user_input'; details: { command?: string; reason?: string; kind?: string; questions?: InputQuestion[] }; status: 'pending' | 'completed' | 'expired' | 'cancelled' }
export type UsageWindow = { used_percent?: number; window_duration_mins?: number; resets_at?: number }
export type UsageLimit = { limit_id?: string; limit_name?: string; primary?: UsageWindow; secondary?: UsageWindow }
export type Usage = { status: 'available' | 'unsupported' | 'error'; rate_limits: UsageLimit | null; rate_limits_by_id: Record<string, UsageLimit>; ordinary_usage_allowed: boolean | null }

type ServerEvent =
  | { type: 'ready' }
  | { type: 'capabilities'; models: ModelCapability[]; collaboration_modes: CollaborationCapability[]; user_input: 'supported' | 'unsupported' }
  | { type: 'usage' } & Usage
  | { type: 'usage_update'; rate_limits: UsageLimit }
  | { type: 'pending_request'; id: string; kind: PendingRequest['kind']; details: PendingRequest['details'] }
  | { type: 'request_outcome'; id: string; status: Exclude<PendingRequest['status'], 'pending'> }
  | { type: 'conversation_list'; conversations: ConversationInfo[] }
  | { type: 'project_list'; projects: ProjectInfo[]; selected_id: string }
  | { type: 'project_selected'; id: string }
  | { type: 'conversation_selected'; conversation: ConversationInfo; messages: Message[] }
  | { type: 'turn_started' }
  | { type: 'steer_accepted'; text: string }
  | { type: 'assistant_delta'; text: string }
  | { type: 'agent_status'; status: string }
  | { type: 'turn_completed'; status: 'completed' | 'failed' | 'interrupted' }
  | { type: 'error'; code: string }

const savedConversationKey = 'remote-codex-chat.conversation-id'
const savedProjectKey = 'remote-codex-chat.project-id'
const savedModelKey = 'remote-codex-chat.model-id'
const savedEffortKey = 'remote-codex-chat.reasoning-effort'

function isConversation(value: unknown): value is ConversationInfo {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return ['id', 'project_id', 'title', 'created_at', 'updated_at'].every(key => typeof item[key] === 'string')
}

function isProject(value: unknown): value is ProjectInfo {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return typeof item.id === 'string' && typeof item.name === 'string'
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
    if (event.type === 'pending_request' && typeof event.id === 'string' && ['command', 'file_change', 'user_input'].includes(String(event.kind)) && event.details && typeof event.details === 'object') return event as ServerEvent
    if (event.type === 'request_outcome' && typeof event.id === 'string' && ['completed', 'expired', 'cancelled'].includes(String(event.status))) return event as ServerEvent
    if (event.type === 'capabilities' && Array.isArray(event.models) && event.models.every(isModel) && Array.isArray(event.collaboration_modes) && event.collaboration_modes.every(isMode)) return event as ServerEvent
    if (event.type === 'usage' && ['available', 'unsupported', 'error'].includes(String(event.status)) && (event.rate_limits === null || isUsageLimit(event.rate_limits)) && isUsageMap(event.rate_limits_by_id) && (event.ordinary_usage_allowed === null || typeof event.ordinary_usage_allowed === 'boolean')) return event as ServerEvent
    if (event.type === 'usage_update' && isUsageLimit(event.rate_limits)) return event as ServerEvent
    if (event.type === 'steer_accepted' && typeof event.text === 'string') return event as ServerEvent
    if (event.type === 'conversation_list' && Array.isArray(event.conversations) && event.conversations.every(isConversation)) return event as ServerEvent
    if (event.type === 'project_list' && Array.isArray(event.projects) && event.projects.every(isProject) && typeof event.selected_id === 'string') return event as ServerEvent
    if (event.type === 'project_selected' && typeof event.id === 'string') return event as ServerEvent
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

function isUsageWindow(value: unknown): value is UsageWindow {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const window = value as Record<string, unknown>
  return ['used_percent', 'window_duration_mins', 'resets_at'].every(key => window[key] === undefined || (typeof window[key] === 'number' && Number.isFinite(window[key])))
}

function isUsageLimit(value: unknown): value is UsageLimit {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const limit = value as Record<string, unknown>
  return ['limit_id', 'limit_name'].every(key => limit[key] === undefined || typeof limit[key] === 'string') && ['primary', 'secondary'].every(key => limit[key] === undefined || isUsageWindow(limit[key]))
}

function isUsageMap(value: unknown): value is Record<string, UsageLimit> {
  return !!value && typeof value === 'object' && !Array.isArray(value) && Object.values(value).every(isUsageLimit)
}

export function useChat() {
  const socket = useRef<WebSocket | null>(null)
  const selectedIdRef = useRef<string | null>(null)
  const selectionPendingRef = useRef(false)
  const projectSelectionPendingRef = useRef(false)
  const pendingPromptRef = useRef<string | null>(null)
  const [connection, setConnection] = useState<Connection>('connecting')
  const [turn, setTurn] = useState<Turn>('idle')
  const [agentStatus, setAgentStatus] = useState('idle')
  const [messages, setMessages] = useState<Message[]>([])
  const [conversations, setConversations] = useState<ConversationInfo[]>([])
  const [projects, setProjects] = useState<ProjectInfo[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
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
  const [requests, setRequests] = useState<PendingRequest[]>([])
  const [userInput, setUserInput] = useState<'supported' | 'unsupported'>('unsupported')
  const [usage, setUsage] = useState<Usage | null>(null)

  useEffect(() => {
    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    let disposed = false
    let retry: ReturnType<typeof setTimeout> | undefined
    function connect() {
      if (disposed) return
      setConnection(socket.current ? 'reconnecting' : 'connecting')
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
            ws.send(JSON.stringify({ type: 'list_projects' }))
            ws.send(JSON.stringify({ type: 'list_capabilities' }))
            ws.send(JSON.stringify({ type: 'read_usage' }))
            break
          case 'usage': setUsage({ status: event.status, rate_limits: event.rate_limits, rate_limits_by_id: event.rate_limits_by_id, ordinary_usage_allowed: event.ordinary_usage_allowed }); break
          case 'usage_update': setUsage(previous => {
            if (previous?.status !== 'available') return previous
            const id = event.rate_limits.limit_id
            const prior = id ? previous.rate_limits_by_id[id] ?? (previous.rate_limits?.limit_id === id ? previous.rate_limits : undefined) : undefined
            const merge = (current: UsageLimit | null | undefined): UsageLimit => ({ ...current, ...event.rate_limits,
              primary: current?.primary || event.rate_limits.primary ? { ...current?.primary, ...event.rate_limits.primary } : undefined,
              secondary: current?.secondary || event.rate_limits.secondary ? { ...current?.secondary, ...event.rate_limits.secondary } : undefined })
            return { ...previous,
              rate_limits: !id || previous.rate_limits?.limit_id === id ? merge(previous.rate_limits) : previous.rate_limits,
              rate_limits_by_id: id ? { ...previous.rate_limits_by_id, [id]: merge(prior) } : previous.rate_limits_by_id }
          }); break
          case 'project_list': {
            setProjects(event.projects)
            const saved = window.localStorage.getItem(savedProjectKey)
            const choice = event.projects.find(item => item.id === saved)?.id ?? event.selected_id
            projectSelectionPendingRef.current = true
            setSelecting(true)
            ws.send(JSON.stringify({ type: 'select_project', id: choice }))
            break
          }
          case 'project_selected':
            projectSelectionPendingRef.current = false
            selectionPendingRef.current = false
            selectedIdRef.current = null
            setSelectedProjectId(event.id)
            if (window.localStorage.getItem(savedProjectKey) !== event.id) window.localStorage.removeItem(savedConversationKey)
            window.localStorage.setItem(savedProjectKey, event.id)
            setSelectedId(null)
            setConversations([])
            setMessages([])
            setTurn('idle')
            setSelecting(false)
            setError(null)
            ws.send(JSON.stringify({ type: 'list_conversations' }))
            break
          case 'capabilities': {
            setUserInput(event.user_input)
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
          case 'pending_request':
            setRequests(previous => [...previous, { id: event.id, kind: event.kind, details: event.details, status: 'pending' }])
            break
          case 'request_outcome':
            setRequests(previous => previous.map(request => request.id === event.id ? { ...request, status: event.status } : request))
            break
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
          case 'turn_completed': setTurn(event.status); setActiveTurn(false); setStopPending(false); setAgentStatus(event.status); ws.send(JSON.stringify({ type: 'read_usage' })); break
          case 'error': {
            setError(event.code)
            if (event.code === 'stop_failed') setStopPending(false)
            if (event.code === 'codex_failure') { setActiveTurn(false); setStopPending(false) }
            if (pendingPromptRef.current !== null) {
              const pending = pendingPromptRef.current
              pendingPromptRef.current = null
              setMessages(previous => previous.at(-1)?.role === 'user' && previous.at(-1)?.text === pending ? previous.slice(0, -1) : previous)
              setTurn('idle')
              setActiveTurn(false)
            }
            const wasSelecting = selectionPendingRef.current
            const wasSelectingProject = projectSelectionPendingRef.current
            projectSelectionPendingRef.current = false
            selectionPendingRef.current = false
            setSelecting(false)
            if (wasSelecting || (!wasSelectingProject && (event.code === 'thread_unavailable' || event.code === 'conversation_not_found'))) {
              selectedIdRef.current = null
              setSelectedId(null)
              setMessages([])
              window.localStorage.removeItem(savedConversationKey)
            }
            if (!['invalid_message', 'turn_in_progress', 'no_active_turn', 'steer_failed', 'stop_failed', 'model_unavailable', 'reasoning_unavailable', 'collaboration_unavailable'].includes(event.code)) setTurn('failed')
            break
          }
        }
      }
      ws.onclose = () => {
        if (disposed || socket.current !== ws) return
        setConnection('disconnected')
        setRequests(previous => previous.map(request => request.status === 'pending' ? { ...request, status: 'cancelled' } : request))
        setModels([])
        setUsage(null)
        setCollaborationModes([])
        setStopPending(false)
        setActiveTurn(false)
        setTurn(current => current === 'running' ? 'failed' : current)
        selectionPendingRef.current = false
        projectSelectionPendingRef.current = false
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
    setRequests([])
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
    const preset = collaborationModes.find(item => item.mode === mode)
    const model = preset?.model ? models.find(item => item.model === preset.model || item.id === preset.model) : models.find(item => item.id === selectedModelId)
    if (model && model.id !== selectedModelId) {
      setSelectedModelId(model.id)
      window.localStorage.setItem(savedModelKey, model.id)
    }
    if (model) {
      const effort = preset?.reasoning_effort && model.reasoning_efforts.includes(preset.reasoning_effort)
        ? preset.reasoning_effort
        : model.id !== selectedModelId || !selectedEffort || !model.reasoning_efforts.includes(selectedEffort)
          ? model.default_reasoning_effort ?? model.reasoning_efforts[0] ?? null
          : selectedEffort
      setSelectedEffort(effort)
      if (effort) window.localStorage.setItem(savedEffortKey, effort)
      else window.localStorage.removeItem(savedEffortKey)
    }
  }

  function refreshCapabilities(): void {
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type: 'list_capabilities' }))
  }

  function refreshUsage(): void {
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type: 'read_usage' }))
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
    if (socket.current?.readyState !== WebSocket.OPEN || turn === 'running' || selectionPendingRef.current || projectSelectionPendingRef.current) return
    selectionPendingRef.current = true
    setSelecting(true)
    socket.current.send(JSON.stringify({ type: 'new_conversation' }))
  }

  function selectConversation(id: string): void {
    if (socket.current?.readyState !== WebSocket.OPEN || turn === 'running' || selectionPendingRef.current || projectSelectionPendingRef.current || id === selectedId) return
    selectionPendingRef.current = true
    setSelecting(true)
    socket.current.send(JSON.stringify({ type: 'select_conversation', id }))
  }

  function selectProject(id: string): void {
    if (socket.current?.readyState !== WebSocket.OPEN || turn === 'running' || selectionPendingRef.current || projectSelectionPendingRef.current || id === selectedProjectId || !projects.some(item => item.id === id)) return
    projectSelectionPendingRef.current = true
    setSelecting(true)
    socket.current.send(JSON.stringify({ type: 'select_project', id }))
  }

  function answerApproval(id: string, decision: 'accept' | 'decline'): void {
    if (socket.current?.readyState !== WebSocket.OPEN || !requests.some(request => request.id === id && request.status === 'pending' && request.kind !== 'user_input')) return
    socket.current.send(JSON.stringify({ type: 'answer_approval', id, decision }))
  }

  function answerUserInput(id: string, answers: Record<string, string[]>): void {
    if (socket.current?.readyState !== WebSocket.OPEN || !requests.some(request => request.id === id && request.status === 'pending' && request.kind === 'user_input')) return
    socket.current.send(JSON.stringify({ type: 'answer_user_input', id, answers }))
  }

  return { connection, turn, activeTurn, agentStatus, messages, conversations, projects, selectedProjectId, selectedId, selecting, error, models, collaborationModes, selectedModelId, selectedEffort, selectedMode, stopPending, requests, userInput, usage, answerApproval, answerUserInput, send, steer, stop, selectModel, selectEffort, selectMode, refreshCapabilities, refreshUsage, newConversation, selectConversation, selectProject }
}
