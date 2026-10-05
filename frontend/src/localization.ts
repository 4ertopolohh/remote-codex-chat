const durationForms = {
  minute: ['минута', 'минуты', 'минут'] as const,
  hour: ['час', 'часа', 'часов'] as const,
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
  if (minutes % 60 === 0) {
    const hours = minutes / 60
    return `${hours} ${russianPlural(hours, durationForms.hour)}`
  }
  return `${minutes} ${russianPlural(minutes, durationForms.minute)}`
}

export function displayConversationTitle(title: string): string {
  return title === 'New conversation' ? 'Новый чат' : title
}
