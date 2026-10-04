// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react'
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

test('visual viewport movement preserves the reader position in a long request', () => {
  vi.stubGlobal('WebSocket', FakeSocket)
  const viewport = new EventTarget()
  Object.defineProperty(viewport, 'height', { value: 400 })
  vi.stubGlobal('visualViewport', viewport)
  render(<App />)
  const dock = document.querySelector('[aria-label="Chat workspace"] > div:last-child') as HTMLDivElement
  Object.defineProperty(dock, 'scrollHeight', { value: 500 })
  dock.scrollTop = 10
  act(() => viewport.dispatchEvent(new Event('scroll')))
  expect(dock.scrollTop).toBe(10)
})

test('keyboard opening for user input preserves its card position', () => {
  vi.stubGlobal('WebSocket', FakeSocket)
  const viewport = new EventTarget()
  let height = 600
  Object.defineProperty(viewport, 'height', { get: () => height })
  vi.stubGlobal('visualViewport', viewport)
  render(<App />)
  FakeSocket.instance.emit({ type: 'pending_request', id: 'request-1', kind: 'user_input', details: { questions: [{ id: 'name', header: 'Name', question: 'What is your name?', options: null, is_other: false, is_secret: false }] } })
  const dock = document.querySelector('[aria-label="Chat workspace"] > div:last-child') as HTMLDivElement
  Object.defineProperty(dock, 'scrollHeight', { value: 500 })
  const field = screen.getByLabelText('Name: What is your name?')
  const reveal = vi.fn()
  field.scrollIntoView = reveal
  field.focus()
  dock.scrollTop = 10
  height = 400
  act(() => viewport.dispatchEvent(new Event('resize')))
  expect(dock.scrollTop).toBe(10)
  expect(reveal).toHaveBeenCalledWith({ block: 'nearest' })
})
