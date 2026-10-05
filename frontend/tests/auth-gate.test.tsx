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
    .mockResolvedValueOnce({ ok: false, status: 401 })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ csrf: 'csrf-test' }) })
    .mockResolvedValueOnce({ ok: true })
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('WebSocket', FakeSocket)
  render(<AuthGate />)
  await screen.findByRole('button', { name: 'Войти' })
  expect(FakeSocket.count).toBe(0)
  fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'test-password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Войти' }))
  await screen.findByText('Неверный пароль. Попробуйте ещё раз.')
  expect(FakeSocket.count).toBe(0)
  fireEvent.click(screen.getByRole('button', { name: 'Войти' }))
  await screen.findByRole('button', { name: 'Выйти' })
  expect(FakeSocket.count).toBe(1)
  expect(fetchMock.mock.calls[2][1].body).toBe(JSON.stringify({ password: 'test-password' }))
  fireEvent.click(screen.getByRole('button', { name: 'Выйти' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Войти' })).toBeTruthy())
  expect(fetchMock.mock.calls[3][1].headers['X-CSRF-Token']).toBe('csrf-test')
})

test('login explains that a forbidden origin does not match the server configuration', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: false, status: 401 })
    .mockResolvedValueOnce({ ok: false, status: 403 })
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('WebSocket', FakeSocket)
  render(<AuthGate />)
  await screen.findByRole('button', { name: 'Войти' })
  fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'test-password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Войти' }))
  await screen.findByText('Адрес сайта не совпадает с настроенным адресом сервера. Проверьте Origin в конфигурации.')
  expect(FakeSocket.count).toBe(0)
})
