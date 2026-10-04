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

test('runtime catalog drives model and reasoning, while active turn offers stop and steer', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  expect(socket.commands()).toContainEqual({ type: 'list_capabilities' })
  socket.emit({ type: 'capabilities', models: [
    { id: 'first', model: 'runtime-first', display_name: 'First', reasoning_efforts: ['low', 'high'], default_reasoning_effort: 'low', is_default: true },
    { id: 'second', model: 'runtime-second', display_name: 'Second', reasoning_efforts: ['medium'], default_reasoning_effort: 'medium', is_default: false },
  ], collaboration_modes: [] })
  expect(screen.queryByLabelText('Mode')).toBeNull()
  socket.emit({ type: 'conversation_selected', conversation: { id: 'c1', project_id: 'default', title: 'Chat', created_at: 'now', updated_at: 'now' }, messages: [] })
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'second' } })
  expect((screen.getByLabelText('Reasoning') as HTMLSelectElement).value).toBe('medium')
  fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'hello' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(socket.commands()).toContainEqual({ type: 'submit_prompt', text: 'hello', model_id: 'second', reasoning_effort: 'medium' })
  expect(screen.getByRole('button', { name: 'Stop' }).hasAttribute('disabled')).toBe(true)
  socket.emit({ type: 'turn_started' })
  fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'change direction' } })
  fireEvent.click(screen.getByRole('button', { name: 'Steer active turn' }))
  expect(socket.commands()).toContainEqual({ type: 'steer_turn', text: 'change direction' })
  fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
  expect(socket.commands()).toContainEqual({ type: 'stop_turn' })
  expect(screen.getByRole('button', { name: 'Stop' }).hasAttribute('disabled')).toBe(true)
})

test('approval card sends only a pending decision and shows its outcome', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  socket.emit({ type: 'pending_request', id: 'opaque-1', kind: 'command', details: { command: 'echo RC006_OK', cwd: 'C:\\repo' } })
  expect(screen.getByLabelText('Approval required')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
  expect(socket.commands()).toContainEqual({ type: 'answer_approval', id: 'opaque-1', decision: 'accept' })
  expect(screen.getByRole('button', { name: 'Approve' }).hasAttribute('disabled')).toBe(true)
  socket.emit({ type: 'request_outcome', id: 'opaque-1', status: 'completed' })
  expect(screen.getByText('Request completed.')).toBeTruthy()
})

test('user input card returns the selected answer shape', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  socket.emit({ type: 'pending_request', id: 'opaque-2', kind: 'user_input', details: { questions: [{ id: 'choice', header: 'Choice', question: 'Continue?', options: [{ label: 'Yes', description: 'Proceed' }], is_other: false, is_secret: false }] } })
  expect(screen.getByLabelText('User input required')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Choice: Continue?'), { target: { value: 'Yes' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send answer' }))
  expect(socket.commands()).toContainEqual({ type: 'answer_user_input', id: 'opaque-2', answers: { choice: ['Yes'] } })
})

test('missing persisted model falls back to runtime default', () => {
  window.localStorage.setItem('remote-codex-chat.model-id', 'removed')
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'capabilities', models: [
    { id: 'fresh', model: 'runtime-fresh', display_name: 'Fresh', reasoning_efforts: ['high'], default_reasoning_effort: 'high', is_default: true },
  ], collaboration_modes: [] })
  expect((screen.getByLabelText('Model') as HTMLSelectElement).value).toBe('fresh')
  expect(window.localStorage.getItem('remote-codex-chat.model-id')).toBe('fresh')
})

test('rejected stale model restores composer and removes unsent prompt', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'capabilities', models: [
    { id: 'old', model: 'old', display_name: 'Old', reasoning_efforts: ['low'], default_reasoning_effort: 'low', is_default: true },
  ], collaboration_modes: [] })
  socket.emit({ type: 'ready' })
  socket.emit({ type: 'conversation_selected', conversation: { id: 'c1', project_id: 'default', title: 'Chat', created_at: 'now', updated_at: 'now' }, messages: [] })
  fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'hello' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  socket.emit({ type: 'error', code: 'model_unavailable' })
  expect(screen.queryByText('hello')).toBeNull()
  expect(screen.getByRole('button', { name: 'Send' }).hasAttribute('disabled')).toBe(true)
  expect(screen.queryByRole('button', { name: 'Steer active turn' })).toBeNull()
})

test('catalog refresh replaces removed model and effort', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'capabilities', models: [
    { id: 'old', model: 'old', display_name: 'Old', reasoning_efforts: ['max'], default_reasoning_effort: 'max', is_default: true },
  ], collaboration_modes: [] })
  socket.emit({ type: 'capabilities', models: [
    { id: 'new', model: 'new', display_name: 'New', reasoning_efforts: ['low'], default_reasoning_effort: 'low', is_default: true },
  ], collaboration_modes: [] })
  expect((screen.getByLabelText('Model') as HTMLSelectElement).value).toBe('new')
  expect((screen.getByLabelText('Reasoning') as HTMLSelectElement).value).toBe('low')
  expect(window.localStorage.getItem('remote-codex-chat.model-id')).toBe('new')
})

test('discovered experimental mode is shown and sent for a new turn', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  socket.emit({ type: 'capabilities', models: [
    { id: 'first', model: 'first', display_name: 'First', reasoning_efforts: ['medium'], default_reasoning_effort: 'medium', is_default: true },
  ], collaboration_modes: [{ name: 'Plan', mode: 'plan', model: null, reasoning_effort: 'medium' }] })
  socket.emit({ type: 'conversation_selected', conversation: { id: 'c1', project_id: 'default', title: 'Chat', created_at: 'now', updated_at: 'now' }, messages: [] })
  fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'plan' } })
  fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'make a plan' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(socket.commands()).toContainEqual({ type: 'submit_prompt', text: 'make a plan', model_id: 'first', reasoning_effort: 'medium', collaboration_mode: 'plan' })
})

test('mode preset updates displayed reasoning and a failed stop restores controls', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  socket.emit({ type: 'capabilities', models: [
    { id: 'first', model: 'first', display_name: 'First', reasoning_efforts: ['low', 'medium'], default_reasoning_effort: 'low', is_default: true },
    { id: 'second', model: 'runtime-second', display_name: 'Second', reasoning_efforts: ['medium'], default_reasoning_effort: 'medium', is_default: false },
  ], collaboration_modes: [{ name: 'Plan', mode: 'plan', model: 'runtime-second', reasoning_effort: 'medium' }] })
  socket.emit({ type: 'conversation_selected', conversation: { id: 'c1', project_id: 'default', title: 'Chat', created_at: 'now', updated_at: 'now' }, messages: [] })
  fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'plan' } })
  expect((screen.getByLabelText('Model') as HTMLSelectElement).value).toBe('second')
  expect((screen.getByLabelText('Reasoning') as HTMLSelectElement).value).toBe('medium')
  fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'plan it' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  socket.emit({ type: 'turn_started' })
  fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
  socket.emit({ type: 'error', code: 'stop_failed' })
  expect(screen.getByRole('button', { name: 'Stop' }).hasAttribute('disabled')).toBe(false)
  expect(screen.getByRole('button', { name: 'Steer active turn' }).hasAttribute('disabled')).toBe(true)
})
