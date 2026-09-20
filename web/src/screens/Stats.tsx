import { useEffect, useState } from 'react'
import { api, type Stats as StatsData } from '../api'
import { duration } from '../format'
import { StatTile } from '../components/StatTile'

export function Stats() {
  const [data, setData] = useState<StatsData | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get<StatsData>('/api/stats')
      .then(setData)
      .catch((e) => setError(e.message))
  }, [])

  return (
    <div className="h-full overflow-y-auto quiet-scroll px-4 py-5 safe-top">
      <h1 className="numeral text-[28px] mb-5">Статистика</h1>

      {error && (
        <p className="text-[14px]" style={{ color: '#D8412F' }}>
          {error}
        </p>
      )}

      {data && (
        <div className="grid gap-3 sm:grid-cols-2 max-w-3xl">
          <StatTile
            label="Обращений за сутки"
            value={String(data.day)}
            hint={`За неделю ${data.week}`}
            tone="calm"
            delay={0}
          />
          <StatTile
            label="Сейчас в работе"
            value={String(data.open_now)}
            hint={data.open_now === 0 ? 'Очередь пуста' : 'Ждут ответа'}
            tone={data.open_now === 0 ? 'good' : 'warn'}
            delay={0.05}
          />
          <StatTile
            label="Среднее время первого ответа"
            value={duration(data.avg_first_reply_seconds)}
            hint="За всё время"
            delay={0.1}
          />
          <StatTile
            label="Средняя оценка"
            value={data.avg_rating === null ? '—' : data.avg_rating.toFixed(2)}
            hint="Из пяти"
            tone={data.avg_rating !== null && data.avg_rating >= 4 ? 'good' : 'plain'}
            delay={0.15}
          />
        </div>
      )}
    </div>
  )
}
