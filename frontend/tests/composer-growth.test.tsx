// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { MessageInput } from '../src/components/MessageInput/MessageInput'

afterEach(cleanup)

test('long prompts grow the composer within a bounded height and remain scrollable', () => {
  render(<MessageInput onSend={vi.fn(() => true)} onSteer={vi.fn(() => true)} onStop={vi.fn()} running={false} activeTurn={false} stopPending={false} disabled={false} />)
  const textarea = screen.getByRole('textbox', { name: 'Message' }) as HTMLTextAreaElement
  Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 480 })
  fireEvent.change(textarea, { target: { value: 'A long prompt' } })
  expect(textarea.style.height).toBe('192px')
  expect(textarea.style.overflowY).toBe('auto')
})
