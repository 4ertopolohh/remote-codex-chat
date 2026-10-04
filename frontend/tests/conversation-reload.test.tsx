// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { App } from '../src/components/App/App'

const conversations = [
  { id: 'saved-id', project_id: 'default', title: 'Earlier', created_at: '2026-10-04', updated_at: '2026-10-04' },
  { id: 'stale-id', project_id: 'default', title: 'Stale', created_at: '2026-10-04', updated_at: '2026-10-04' },
]

class FakeSocket {
  static OPEN = 1
  static instances: FakeSocket[] = []
  readyState = FakeSocket.OPEN
  sent: string[] = []
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor() { FakeSocket.instances.push(this) }
  send(data: string) { this.sent.push(data) }
  close() { this.readyState = 3; this.onclose?.() }
  emit(payload: object) {
    act(() => this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(payload) })))
  }
  commands(): object[] { return this.sent.map(item => JSON.parse(item) as object) }
}

beforeEach(() => {
  window.localStorage.clear()
  FakeSocket.instances = []
  vi.stubGlobal('WebSocket', FakeSocket)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

test('reload reselects the saved conversation and renders restored history', () => {
  window.localStorage.setItem('remote-codex-chat.conversation-id', 'saved-id')
  const firstPage = render(<App />)
  const firstSocket = FakeSocket.instances[0]
  firstSocket.emit({ type: 'ready' })
  firstSocket.emit({ type: 'conversation_list', conversations })
  expect(firstSocket.commands()).toContainEqual({ type: 'select_conversation', id: 'saved-id' })
  firstSocket.emit({ type: 'conversation_selected', conversation: conversations[0], messages: [{ role: 'user', text: 'Earlier prompt' }] })
  expect(screen.getByText('Earlier prompt')).toBeTruthy()
  firstPage.unmount()

  render(<App />)
  const secondSocket = FakeSocket.instances[1]
  secondSocket.emit({ type: 'ready' })
  secondSocket.emit({ type: 'conversation_list', conversations })
  expect(secondSocket.commands()).toContainEqual({ type: 'select_conversation', id: 'saved-id' })
  secondSocket.emit({ type: 'conversation_selected', conversation: conversations[0], messages: [{ role: 'user', text: 'Earlier prompt' }, { role: 'assistant', text: 'Earlier answer' }] })
  expect(screen.getByText('Earlier answer')).toBeTruthy()
})

test('failed switch clears stale transcript and allows a new conversation', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  socket.emit({ type: 'conversation_list', conversations })
  socket.emit({ type: 'conversation_selected', conversation: conversations[0], messages: [{ role: 'user', text: 'Earlier prompt' }] })
  fireEvent.click(screen.getByRole('button', { name: 'Stale' }))
  socket.emit({ type: 'error', code: 'thread_unavailable' })
  expect(screen.queryByText('Earlier prompt')).toBeNull()
  expect(screen.getByRole('button', { name: 'New conversation' }).hasAttribute('disabled')).toBe(false)
})

test('project switch shows only that project conversations and survives reload', () => {
  const projects = [{ id: 'first', name: 'First' }, { id: 'second', name: 'Second' }]
  const page = render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  socket.emit({ type: 'project_list', projects, selected_id: 'first' })
  socket.emit({ type: 'project_selected', id: 'first' })
  socket.emit({ type: 'conversation_list', conversations })
  socket.emit({ type: 'conversation_selected', conversation: conversations[0], messages: [{ role: 'user', text: 'Earlier prompt' }] })
  fireEvent.change(screen.getByRole('combobox', { name: 'Project' }), { target: { value: 'second' } })
  expect(socket.commands()).toContainEqual({ type: 'select_project', id: 'second' })
  socket.emit({ type: 'project_selected', id: 'second' })
  expect(screen.queryByText('Earlier prompt')).toBeNull()
  expect(window.localStorage.getItem('remote-codex-chat.project-id')).toBe('second')
  socket.emit({ type: 'conversation_list', conversations: [] })
  expect(socket.commands()).toContainEqual({ type: 'new_conversation' })
  const secondConversation = { id: 'second-id', project_id: 'second', title: 'New conversation', created_at: '2026-10-05', updated_at: '2026-10-05' }
  socket.emit({ type: 'conversation_selected', conversation: secondConversation, messages: [] })
  page.unmount()
  render(<App />)
  const reloaded = FakeSocket.instances[1]
  reloaded.emit({ type: 'ready' })
  reloaded.emit({ type: 'project_list', projects, selected_id: 'first' })
  expect(reloaded.commands()).toContainEqual({ type: 'select_project', id: 'second' })
  reloaded.emit({ type: 'project_selected', id: 'second' })
  reloaded.emit({ type: 'conversation_list', conversations: [secondConversation] })
  expect(reloaded.commands()).toContainEqual({ type: 'select_conversation', id: 'second-id' })
})
