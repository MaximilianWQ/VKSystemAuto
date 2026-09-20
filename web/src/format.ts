/** Форматирование для интерфейса. Русские склонения делаем честно: «2 минуты»,
    а не «2 минут». */

export function plural(count: number, forms: [string, string, string]): string {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return forms[0]
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return forms[1]
  return forms[2]
}

export function waiting(seconds: number): string {
  if (seconds < 60) return 'только что'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} ${plural(minutes, ['минута', 'минуты', 'минут'])}`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} ${plural(hours, ['час', 'часа', 'часов'])}`
  const days = Math.floor(hours / 24)
  return `${days} ${plural(days, ['день', 'дня', 'дней'])}`
}

export function duration(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 60) return `${Math.round(seconds)} с`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} мин`
  return `${(minutes / 60).toFixed(1)} ч`
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

export function dayLabel(iso: string): string {
  const date = new Date(iso)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)

  const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString()
  if (sameDay(date, today)) return 'Сегодня'
  if (sameDay(date, yesterday)) return 'Вчера'
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
}

export function fileSize(bytes: number | undefined): string {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`
}

export function voiceLength(seconds: number | undefined): string {
  const total = Math.max(0, Math.round(seconds ?? 0))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

export function initials(name: string): string {
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}
