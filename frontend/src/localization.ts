const durationForms = {
  minute: ['минута', 'минуты', 'минут'] as const,
  hour: ['час', 'часа', 'часов'] as const,
  day: ['день', 'дня', 'дней'] as const,
}

function russianPlural(value: number, [one, few, many]: readonly [string, string, string]): string {
  const integer = Math.abs(Math.trunc(value))
  const lastTwo = integer % 100
  if (lastTwo >= 11 && lastTwo <= 14) return many
  const lastDigit = integer % 10
  if (lastDigit === 1) return one
  if (lastDigit >= 2 && lastDigit <= 4) return few
  return many
}

export function formatRussianDuration(minutes: number): string {
  const wholeHours = Math.floor(minutes / 60)
  const days = Math.floor(wholeHours / 24)
  const hours = wholeHours % 24
  const remainingMinutes = minutes % 60
  const parts: string[] = []
  if (days > 0) parts.push(`${days} ${russianPlural(days, durationForms.day)}`)
  if (hours > 0) parts.push(`${hours} ${russianPlural(hours, durationForms.hour)}`)
  if (remainingMinutes > 0 && days === 0 && hours === 0) parts.push(`${remainingMinutes} ${russianPlural(remainingMinutes, durationForms.minute)}`)
  return parts.join(' ') || `0 ${russianPlural(0, durationForms.hour)}`
}

export function displayConversationTitle(title: string): string {
  return title === 'New conversation' ? 'Новый чат' : title
}
