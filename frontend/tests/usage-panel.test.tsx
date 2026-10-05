// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { App } from '../src/components/App/App'

class FakeSocket {
  static OPEN = 1
  static instances: FakeSocket[] = []
  readyState = FakeSocket.OPEN
  sent: string[] = []
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onclose: (() => void) | null = null
  constructor() { FakeSocket.instances.push(this) }
  send(value: string) { this.sent.push(value) }
  close() { this.readyState = 3; this.onclose?.() }
  emit(value: object) { act(() => this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(value) }))) }
  commands(): object[] { return this.sent.map(value => JSON.parse(value) as object) }
}

beforeEach(() => { window.localStorage.clear(); FakeSocket.instances = []; vi.stubGlobal('WebSocket', FakeSocket) })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('usage displays only runtime values for flexible and sparse limits', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  expect(socket.commands()).toContainEqual({ type: 'read_usage' })
  socket.emit({ type: 'usage', status: 'available', rate_limits: null, rate_limits_by_id: {
    custom_bucket: { limit_name: 'Custom', primary: { used_percent: 42, resets_at: 1_800_000_000 }, secondary: { used_percent: 7 } },
    sparse: { primary: { window_duration_mins: 60 } },
  }, ordinary_usage_allowed: null })
  expect(screen.getByText('Custom')).toBeTruthy()
  expect(screen.getByText('42% used')).toBeTruthy()
  expect(screen.getByText('7% used')).toBeTruthy()
  expect(screen.getByText('sparse')).toBeTruthy()
  expect(screen.queryByText('Reset now')).toBeNull()
})

test('usage errors remain local and chat remains usable', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  socket.emit({ type: 'usage', status: 'error', rate_limits: null, rate_limits_by_id: {}, ordinary_usage_allowed: null })
  expect(screen.getByText('Usage information is unavailable')).toBeTruthy()
  socket.emit({ type: 'conversation_selected', conversation: { id: 'c1', project_id: 'default', title: 'Chat', created_at: 'now', updated_at: 'now' }, messages: [] })
  fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'hello' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(socket.commands()).toContainEqual({ type: 'submit_prompt', text: 'hello' })
})

test('sparse runtime updates keep known windows and unsupported runtime is explicit', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'usage', status: 'unsupported', rate_limits: null, rate_limits_by_id: {}, ordinary_usage_allowed: null })
  expect(screen.getByText('Usage information is not supported by this Codex runtime.')).toBeTruthy()
  socket.emit({ type: 'usage', status: 'available', rate_limits: { limit_id: 'dynamic', primary: { used_percent: 10, window_duration_mins: 60 } }, rate_limits_by_id: {}, ordinary_usage_allowed: null })
  socket.emit({ type: 'usage_update', rate_limits: { limit_id: 'dynamic', primary: { used_percent: 20 } } })
  expect(screen.getByText('20% used')).toBeTruthy()
  expect(screen.getByText('60 min window')).toBeTruthy()
  socket.emit({ type: 'turn_completed', status: 'completed' })
  expect(socket.commands()).toContainEqual({ type: 'read_usage' })
})

test('a newly announced runtime bucket becomes visible', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'usage', status: 'available', rate_limits: null, rate_limits_by_id: { first: { primary: { used_percent: 10 } } }, ordinary_usage_allowed: null })
  socket.emit({ type: 'usage_update', rate_limits: { limit_id: 'new_bucket', primary: { used_percent: 25 } } })
  expect(screen.getByText('new_bucket')).toBeTruthy()
  expect(screen.getByText('25% used')).toBeTruthy()
})
