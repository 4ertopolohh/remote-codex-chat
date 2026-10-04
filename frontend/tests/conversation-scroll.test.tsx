// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'
import { Conversation } from '../src/components/Conversation/Conversation'

afterEach(cleanup)

test('stream follows the bottom until the reader scrolls upward', () => {
  const view = render(<Conversation messages={[{ role: 'assistant', text: 'First' }]} />)
  const region = screen.getByRole('region', { name: 'Conversation' })
  let height = 400
  Object.defineProperties(region, {
    clientHeight: { configurable: true, get: () => 200 },
    scrollHeight: { configurable: true, get: () => height },
  })
  region.scrollTop = 200
  fireEvent.scroll(region)
  height = 500
  view.rerender(<Conversation messages={[{ role: 'assistant', text: 'First and more' }]} />)
  expect(region.scrollTop).toBe(300)

  region.scrollTop = 40
  fireEvent.scroll(region)
  height = 600
  view.rerender(<Conversation messages={[{ role: 'assistant', text: 'First and much more' }]} />)
  expect(region.scrollTop).toBe(40)
})

test('switching conversations starts at the latest message after reading older content', () => {
  const view = render(<Conversation conversationId="first" messages={[{ role: 'assistant', text: 'Earlier' }]} />)
  const region = screen.getByRole('region', { name: 'Conversation' })
  Object.defineProperties(region, {
    clientHeight: { configurable: true, get: () => 200 },
    scrollHeight: { configurable: true, get: () => 500 },
  })
  region.scrollTop = 40
  fireEvent.scroll(region)
  view.rerender(<Conversation conversationId="second" messages={[{ role: 'assistant', text: 'Latest' }]} />)
  expect(region.scrollTop).toBe(300)
})

test('an unfinished streamed code fence remains a scrollable code block', () => {
  const view = render(<Conversation messages={[{ role: 'assistant', text: 'Example:\n```js\nconst veryLongLine = "abcdefghijklmnopqrstuvwxyz"' }]} />)
  expect(view.container.querySelector('pre')?.textContent).toContain('const veryLongLine')
  view.rerender(<Conversation messages={[{ role: 'assistant', text: 'Example:\n```js\nconst veryLongLine = "abcdefghijklmnopqrstuvwxyz"\n```' }]} />)
  expect(view.container.querySelector('pre')?.textContent).toContain('const veryLongLine')
})
