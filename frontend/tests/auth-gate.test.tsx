// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { AuthGate } from '../src/components/AuthGate/AuthGate'

class FakeSocket {
  static count = 0
  constructor() { FakeSocket.count++ }
  close() {}
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); FakeSocket.count = 0 })

test('chat connects only after a successful password login and logout revokes the UI session', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: false, status: 401 })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ csrf: 'csrf-test' }) })
    .mockResolvedValueOnce({ ok: true })
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('WebSocket', FakeSocket)
  render(<AuthGate />)
  await screen.findByRole('button', { name: 'Sign in' })
  expect(FakeSocket.count).toBe(0)
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'test-password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  await screen.findByRole('button', { name: 'Sign out' })
  expect(FakeSocket.count).toBe(1)
  expect(fetchMock.mock.calls[1][1].body).toBe(JSON.stringify({ password: 'test-password' }))
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Sign in' })).toBeTruthy())
  expect(fetchMock.mock.calls[2][1].headers['X-CSRF-Token']).toBe('csrf-test')
})
