import { useEffect, useRef, useState } from 'react'

type Connection = 'connecting' | 'connected' | 'disconnected'
type Turn = 'idle' | 'running' | 'completed' | 'failed' | 'interrupted'
export type Message = { role: 'user' | 'assistant'; text: string }
export type ConversationInfo = { id: string; project_id: string; title: string; created_at: string; updated_at: string }

type ServerEvent =
  | { type: 'ready' }
  | { type: 'conversation_list'; conversations: ConversationInfo[] }
  | { type: 'conversation_selected'; conversation: ConversationInfo; messages: Message[] }
  | { type: 'turn_started' }
  | { type: 'assistant_delta'; text: string }
  | { type: 'agent_status'; status: string }
  | { type: 'turn_completed'; status: 'completed' | 'failed' | 'interrupted' }
  | { type: 'error'; code: string }

const savedConversationKey = 'remote-codex-chat.conversation-id'

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
    if (event.type === 'conversation_list' && Array.isArray(event.conversations) && event.conversations.every(isConversation)) return event as ServerEvent
    if (event.type === 'conversation_selected' && isConversation(event.conversation) && Array.isArray(event.messages) && event.messages.every(isMessage)) return event as ServerEvent
    if (event.type === 'assistant_delta' && typeof event.text === 'string') return event as ServerEvent
    if (event.type === 'agent_status' && typeof event.status === 'string') return event as ServerEvent
    if (event.type === 'turn_completed' && ['completed', 'failed', 'interrupted'].includes(String(event.status))) return event as ServerEvent
    if (event.type === 'error' && typeof event.code === 'string') return event as ServerEvent
  } catch { /* Ignore malformed server data. */ }
  return null
}

export function useChat() {
  const socket = useRef<WebSocket | null>(null)
  const selectedIdRef = useRef<string | null>(null)
  const selectionPendingRef = useRef(false)
  const [connection, setConnection] = useState<Connection>('connecting')
  const [turn, setTurn] = useState<Turn>('idle')
  const [agentStatus, setAgentStatus] = useState('idle')
  const [messages, setMessages] = useState<Message[]>([])
  const [conversations, setConversations] = useState<ConversationInfo[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selecting, setSelecting] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
          case 'turn_started': setTurn('running'); setAgentStatus('starting'); break
          case 'assistant_delta':
            setMessages(previous => {
              const last = previous.at(-1)
              if (last?.role === 'assistant') return [...previous.slice(0, -1), { role: 'assistant', text: last.text + event.text }]
              return [...previous, { role: 'assistant', text: event.text }]
            })
            break
          case 'agent_status': setAgentStatus(event.status); break
          case 'turn_completed': setTurn(event.status); setAgentStatus(event.status); break
          case 'error': {
            setError(event.code)
            const wasSelecting = selectionPendingRef.current
            selectionPendingRef.current = false
            setSelecting(false)
            if (wasSelecting || event.code === 'thread_unavailable' || event.code === 'conversation_not_found') {
              selectedIdRef.current = null
              setSelectedId(null)
              setMessages([])
              window.localStorage.removeItem(savedConversationKey)
            }
            if (event.code !== 'invalid_message' && event.code !== 'turn_in_progress') setTurn('failed')
            break
          }
        }
      }
      ws.onclose = () => {
        if (disposed || socket.current !== ws) return
        setConnection('disconnected')
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
    socket.current.send(JSON.stringify({ type: 'submit_prompt', text }))
    setMessages(previous => [...previous, { role: 'user', text }])
    setTurn('running')
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

  return { connection, turn, agentStatus, messages, conversations, selectedId, selecting, error, send, newConversation, selectConversation }
}
