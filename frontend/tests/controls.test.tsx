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

beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear(); FakeSocket.instances = []; vi.stubGlobal('WebSocket', FakeSocket) })
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
  expect(screen.queryByLabelText('Режим')).toBeNull()
  expect(screen.getByRole('option', { name: 'Низкий' })).toBeTruthy()
  socket.emit({ type: 'conversation_selected', conversation: { id: 'c1', project_id: 'default', title: 'Chat', created_at: 'now', updated_at: 'now' }, messages: [] })
  fireEvent.change(screen.getByLabelText('Модель'), { target: { value: 'second' } })
  expect((screen.getByLabelText('Уровень рассуждений') as HTMLSelectElement).value).toBe('medium')
  fireEvent.change(screen.getByLabelText('Сообщение'), { target: { value: 'hello' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))
  expect(socket.commands()).toContainEqual(expect.objectContaining({ type: 'submit_prompt', text: 'hello', model_id: 'second', reasoning_effort: 'medium', request_id: expect.any(String) }))
  expect(screen.getByRole('button', { name: 'Остановить' }).hasAttribute('disabled')).toBe(true)
  socket.emit({ type: 'turn_started' })
  fireEvent.change(screen.getByLabelText('Сообщение'), { target: { value: 'change direction' } })
  fireEvent.click(screen.getByRole('button', { name: 'Направить ответ' }))
  expect(socket.commands()).toContainEqual({ type: 'steer_turn', text: 'change direction' })
  fireEvent.click(screen.getByRole('button', { name: 'Остановить' }))
  expect(socket.commands()).toContainEqual({ type: 'stop_turn' })
  expect(screen.getByRole('button', { name: 'Остановить' }).hasAttribute('disabled')).toBe(true)
})

test('approval card sends only a pending decision and shows its outcome', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  socket.emit({ type: 'pending_request', id: 'opaque-1', kind: 'command', details: { command: 'echo RC006_OK', cwd: 'C:\\repo' } })
  expect(screen.getByLabelText('Требуется одобрение')).toBeTruthy()
  expect(screen.queryByText('C:\\repo')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Одобрить' }))
  expect(socket.commands()).toContainEqual({ type: 'answer_approval', id: 'opaque-1', decision: 'accept' })
  expect(screen.getByRole('button', { name: 'Одобрить' }).hasAttribute('disabled')).toBe(true)
  socket.emit({ type: 'request_outcome', id: 'opaque-1', status: 'completed' })
  expect(screen.getByRole('heading', { name: 'Запрос: выполнен' })).toBeTruthy()
})

test('a lost connection has distinct offline and reconnecting states', () => {
  vi.useFakeTimers()
  try {
    render(<App />)
    const socket = FakeSocket.instances[0]
    socket.emit({ type: 'ready' })
    act(() => socket.onclose?.())
    expect(screen.getByText('Нет связи')).toBeTruthy()
    act(() => vi.advanceTimersByTime(500))
    expect(FakeSocket.instances).toHaveLength(2)
    expect(screen.getByText('Переподключаемся')).toBeTruthy()
  } finally {
    vi.useRealTimers()
  }
})

test('lost streaming turn remains unknown after reconnect and reload without resubmission', () => {
  vi.useFakeTimers()
  try {
    const conversation = { id: 'c1', project_id: 'default', title: 'Chat', created_at: 'now', updated_at: 'now' }
    const page = render(<App />)
    const first = FakeSocket.instances[0]
    first.emit({ type: 'ready' })
    first.emit({ type: 'conversation_selected', conversation, messages: [] })
    fireEvent.change(screen.getByLabelText('Сообщение'), { target: { value: 'check status' } })
    fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))
    first.emit({ type: 'turn_started' })
    act(() => first.close())
    expect(screen.getByText('Запрос: результат неизвестен')).toBeTruthy()
    act(() => vi.advanceTimersByTime(500))
    const second = FakeSocket.instances[1]
    second.emit({ type: 'ready' })
    second.emit({ type: 'conversation_selected', conversation, messages: [{ role: 'user', text: 'check status' }] })
    expect(screen.getByText('Запрос: результат неизвестен')).toBeTruthy()
    expect(second.commands().filter(command => 'type' in command && command.type === 'submit_prompt')).toHaveLength(0)
    page.unmount()
    render(<App />)
    const third = FakeSocket.instances[2]
    third.emit({ type: 'ready' })
    third.emit({ type: 'conversation_selected', conversation, messages: [{ role: 'user', text: 'check status' }] })
    expect(screen.getByText('Запрос: результат неизвестен')).toBeTruthy()
    expect(third.commands().filter(command => 'type' in command && command.type === 'submit_prompt')).toHaveLength(0)
    expect(screen.getByRole('button', { name: 'Отправить' }).hasAttribute('disabled')).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Я проверил переписку' }))
    expect(screen.getByText('Запрос: ожидает')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Сообщение'), { target: { value: 'new question' } })
    fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))
    expect(third.commands()).toContainEqual(expect.objectContaining({ type: 'submit_prompt', text: 'new question', request_id: expect.any(String) }))
  } finally {
    vi.useRealTimers()
  }
})

test('approval outcome is not claimed after a lost connection', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  socket.emit({ type: 'pending_request', id: 'approval-1', kind: 'command', details: { command: 'echo safe' } })
  act(() => socket.close())
  expect(screen.getByRole('heading', { name: 'Запрос: результат неизвестен' })).toBeTruthy()
  expect(screen.getByText('Связь прервалась, и результат запроса неизвестен. Проверьте переписку, прежде чем продолжить.')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Одобрить' }).hasAttribute('disabled')).toBe(true)
})

test('rejected approval response does not remain in sending state', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  socket.emit({ type: 'conversation_selected', conversation: { id: 'c1', project_id: 'default', title: 'Chat', created_at: 'now', updated_at: 'now' }, messages: [] })
  fireEvent.change(screen.getByLabelText('Сообщение'), { target: { value: 'run' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))
  socket.emit({ type: 'turn_started' })
  socket.emit({ type: 'pending_request', id: 'approval-1', kind: 'command', details: { command: 'echo safe' } })
  fireEvent.click(screen.getByRole('button', { name: 'Одобрить' }))
  socket.emit({ type: 'error', code: 'request_unavailable', id: 'approval-1' })
  expect(screen.getByRole('heading', { name: 'Запрос: результат неизвестен' })).toBeTruthy()
  expect(screen.queryByText('Отправляем ответ…')).toBeNull()
  expect(screen.getByText('Запрос: выполняется')).toBeTruthy()
})

test('repeated connection failures back off and a ready connection resets the delay', () => {
  vi.useFakeTimers()
  try {
    render(<App />)
    act(() => FakeSocket.instances[0].close())
    act(() => vi.advanceTimersByTime(500))
    expect(FakeSocket.instances).toHaveLength(2)
    act(() => FakeSocket.instances[1].close())
    act(() => vi.advanceTimersByTime(999))
    expect(FakeSocket.instances).toHaveLength(2)
    act(() => vi.advanceTimersByTime(1))
    expect(FakeSocket.instances).toHaveLength(3)
    FakeSocket.instances[2].emit({ type: 'ready' })
    act(() => FakeSocket.instances[2].close())
    act(() => vi.advanceTimersByTime(500))
    expect(FakeSocket.instances).toHaveLength(4)
  } finally {
    vi.useRealTimers()
  }
})

test('user input card returns the selected answer shape', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  socket.emit({ type: 'pending_request', id: 'opaque-2', kind: 'user_input', details: { questions: [{ id: 'choice', header: 'Choice', question: 'Continue?', options: [{ label: 'Yes', description: 'Proceed' }], is_other: false, is_secret: false }] } })
  expect(screen.getByLabelText('Нужен ваш ответ')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Choice: Continue?'), { target: { value: 'Yes' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить ответ' }))
  expect(socket.commands()).toContainEqual({ type: 'answer_user_input', id: 'opaque-2', answers: { choice: ['Yes'] } })
})

test('file approval without details requires explicit acknowledgement', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  socket.emit({ type: 'pending_request', id: 'opaque-3', kind: 'file_change', details: {} })
  const approve = screen.getByRole('button', { name: 'Одобрить' })
  expect(approve.hasAttribute('disabled')).toBe(true)
  fireEvent.click(screen.getByRole('checkbox'))
  expect(approve.hasAttribute('disabled')).toBe(false)
  fireEvent.click(approve)
  expect(socket.commands()).toContainEqual({ type: 'answer_approval', id: 'opaque-3', decision: 'accept' })
})

test('file approval with a reason still requires file-scope acknowledgement', () => {
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'ready' })
  socket.emit({ type: 'pending_request', id: 'opaque-4', kind: 'file_change', details: { reason: 'Update proof' } })
  expect(screen.getByRole('button', { name: 'Одобрить' }).hasAttribute('disabled')).toBe(true)
  fireEvent.click(screen.getByRole('checkbox'))
  expect(screen.getByRole('button', { name: 'Одобрить' }).hasAttribute('disabled')).toBe(false)
})

test('missing persisted model falls back to runtime default', () => {
  window.localStorage.setItem('remote-codex-chat.model-id', 'removed')
  render(<App />)
  const socket = FakeSocket.instances[0]
  socket.emit({ type: 'capabilities', models: [
    { id: 'fresh', model: 'runtime-fresh', display_name: 'Fresh', reasoning_efforts: ['high'], default_reasoning_effort: 'high', is_default: true },
  ], collaboration_modes: [] })
  expect((screen.getByLabelText('Модель') as HTMLSelectElement).value).toBe('fresh')
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
  fireEvent.change(screen.getByLabelText('Сообщение'), { target: { value: 'hello' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))
  socket.emit({ type: 'error', code: 'model_unavailable' })
  expect(screen.queryByText('hello')).toBeNull()
  expect(screen.getByRole('button', { name: 'Отправить' }).hasAttribute('disabled')).toBe(true)
  expect(screen.queryByRole('button', { name: 'Направить ответ' })).toBeNull()
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
  expect((screen.getByLabelText('Модель') as HTMLSelectElement).value).toBe('new')
  expect((screen.getByLabelText('Уровень рассуждений') as HTMLSelectElement).value).toBe('low')
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
  fireEvent.change(screen.getByLabelText('Режим'), { target: { value: 'plan' } })
  fireEvent.change(screen.getByLabelText('Сообщение'), { target: { value: 'make a plan' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))
  expect(socket.commands()).toContainEqual(expect.objectContaining({ type: 'submit_prompt', text: 'make a plan', model_id: 'first', reasoning_effort: 'medium', collaboration_mode: 'plan', request_id: expect.any(String) }))
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
  fireEvent.change(screen.getByLabelText('Режим'), { target: { value: 'plan' } })
  expect((screen.getByLabelText('Модель') as HTMLSelectElement).value).toBe('second')
  expect((screen.getByLabelText('Уровень рассуждений') as HTMLSelectElement).value).toBe('medium')
  fireEvent.change(screen.getByLabelText('Сообщение'), { target: { value: 'plan it' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))
  socket.emit({ type: 'turn_started' })
  fireEvent.click(screen.getByRole('button', { name: 'Остановить' }))
  socket.emit({ type: 'error', code: 'stop_failed' })
  expect(screen.getByRole('button', { name: 'Остановить' }).hasAttribute('disabled')).toBe(false)
  expect(screen.getByRole('button', { name: 'Направить ответ' }).hasAttribute('disabled')).toBe(true)
})
