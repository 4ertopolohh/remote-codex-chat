// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { App } from '../src/components/App/App'

class FakeSocket {
  static OPEN = 1
  static instance: FakeSocket
  readyState = FakeSocket.OPEN
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  constructor() { FakeSocket.instance = this }
  send() {}
  close() {}
  emit(payload: object) { act(() => this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(payload) }))) }
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('history surface closes with Escape and restores focus to its trigger', () => {
  vi.stubGlobal('WebSocket', FakeSocket)
  render(<App />)
  const trigger = screen.getByRole('button', { name: 'History' })
  fireEvent.click(trigger)
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  expect(document.activeElement).toBe(trigger)
})

test('closed phone history cannot receive focus and its close button returns focus', () => {
  vi.stubGlobal('WebSocket', FakeSocket)
  vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  render(<App />)
  const trigger = screen.getByRole('button', { name: 'History', exact: true })
  const history = document.getElementById('conversation-history')!
  expect(history.hasAttribute('inert')).toBe(true)
  fireEvent.click(trigger)
  expect(history.hasAttribute('inert')).toBe(false)
  expect(document.activeElement).toBe(within(history).getByRole('button', { name: 'Close history' }))
  fireEvent.click(within(history).getByRole('button', { name: 'Close history' }))
  expect(history.hasAttribute('inert')).toBe(true)
  expect(document.activeElement).toBe(trigger)
})

test('Tab stays inside the open phone history', () => {
  vi.stubGlobal('WebSocket', FakeSocket)
  vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  render(<App />)
  FakeSocket.instance.emit({ type: 'ready' })
  fireEvent.click(screen.getByRole('button', { name: 'History', exact: true }))
  const history = document.getElementById('conversation-history')!
  const close = within(history).getByRole('button', { name: 'Close history' })
  const last = within(history).getByRole('button', { name: 'New conversation' })
  last.focus()
  fireEvent.keyDown(document, { key: 'Tab' })
  expect(document.activeElement).toBe(close)
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
  expect(document.activeElement).toBe(last)
})
