import { useEffect, useRef, useState } from 'react'

type Connection = 'connecting' | 'connected' | 'disconnected'
type Turn = 'idle' | 'running' | 'completed' | 'failed' | 'interrupted'
export type Message = { role: 'user' | 'assistant'; text: string }

type ServerEvent =
  | { type: 'ready' }
  | { type: 'turn_started' }
  | { type: 'assistant_delta'; text: string }
  | { type: 'agent_status'; status: string }
  | { type: 'turn_completed'; status: 'completed' | 'failed' | 'interrupted' }
  | { type: 'error'; code: string }

function parseEvent(data: string): ServerEvent | null {
  try {
    const value: unknown = JSON.parse(data)
    if (!value || typeof value !== 'object' || !('type' in value)) return null
    const event = value as Record<string, unknown>
    if (event.type === 'ready' || event.type === 'turn_started') return event as ServerEvent
    if (event.type === 'assistant_delta' && typeof event.text === 'string') return event as ServerEvent
    if (event.type === 'agent_status' && typeof event.status === 'string') return event as ServerEvent
    if (event.type === 'turn_completed' && ['completed', 'failed', 'interrupted'].includes(String(event.status))) return event as ServerEvent
    if (event.type === 'error' && typeof event.code === 'string') return event as ServerEvent
  } catch { /* Ignore malformed server data. */ }
  return null
}

export function useChat() {
  const socket = useRef<WebSocket | null>(null)
  const [connection, setConnection] = useState<Connection>('connecting')
  const [turn, setTurn] = useState<Turn>('idle')
  const [agentStatus, setAgentStatus] = useState('idle')
  const [messages, setMessages] = useState<Message[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${scheme}//${window.location.host}/ws/chat`)
    socket.current = ws
    ws.onmessage = ({ data }: MessageEvent<string>) => {
      if (socket.current !== ws) return
      const event = parseEvent(data)
      if (!event) return
      switch (event.type) {
        case 'ready': setConnection('connected'); break
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
        case 'error':
          setError(event.code)
          if (event.code !== 'invalid_message' && event.code !== 'turn_in_progress') setTurn('failed')
          break
      }
    }
    ws.onclose = () => { if (socket.current === ws) { setConnection('disconnected'); setTurn(current => current === 'running' ? 'failed' : current) } }
    ws.onerror = () => { if (socket.current === ws) setError('connection_failed') }
    return () => { ws.close(); socket.current = null }
  }, [])

  function send(text: string): boolean {
    if (socket.current?.readyState !== WebSocket.OPEN || connection !== 'connected' || turn === 'running' || !text.trim()) return false
    socket.current.send(JSON.stringify({ type: 'submit_prompt', text }))
    setMessages(previous => [...previous, { role: 'user', text }])
    setTurn('running')
    setError(null)
    return true
  }

  return { connection, turn, agentStatus, messages, error, send }
}
