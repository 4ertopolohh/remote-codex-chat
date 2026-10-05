import { expect, test } from 'vitest'
import { displayConversationTitle, formatRussianDuration } from '../src/localization'

test('Russian duration formatting handles singular, plural, and hour values', () => {
  expect(formatRussianDuration(1)).toBe('1 минута')
  expect(formatRussianDuration(5)).toBe('5 минут')
  expect(formatRussianDuration(21)).toBe('21 минута')
  expect(formatRussianDuration(60)).toBe('1 час')
  expect(formatRussianDuration(120)).toBe('2 часа')
})

test('only the application-generated default conversation title is presented in Russian', () => {
  expect(displayConversationTitle('New conversation')).toBe('Новый чат')
  expect(displayConversationTitle('Generated Codex title')).toBe('Generated Codex title')
})
