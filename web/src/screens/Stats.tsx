import { useEffect, useState } from 'react'
import { api, type Stats as StatsData } from '../api'
import { duration, plural } from '../format'
import { Panel } from '../components/ui'

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Panel className="px-4 py-3.5">
      <div className="text-[12px]" style={{ color: 'var(--muted)' }}>
        {label}
      </div>
      <div className="display text-[30px] mt-1.5">{value}</div>
      {hint && (
        <div className="text-[12px] mt-1" style={{ color: 'var(--muted)' }}>
          {hint}
        </div>
      )}
    </Panel>
  )
}

/** Среднее скрывает картину: две пятёрки и двойка дают те же 4.0, что три
    четвёрки. Распределение показывает, есть ли недовольные. */
function Ratings({ data }: { data: StatsData }) {
  const peak = Math.max(1, ...Object.values(data.ratings))
  const low = (data.ratings['1'] ?? 0) + (data.ratings['2'] ?? 0)

  return (
    <Panel className="px-4 py-3.5">
      <div className="flex items-baseline gap-2">
        <span className="text-[12px]" style={{ color: 'var(--muted)' }}>
          Оценки клиентов
        </span>
        <span className="num text-[12px] ml-auto" style={{ color: 'var(--muted)' }}>
          {data.ratings_total} {plural(data.ratings_total, ['оценка', 'оценки', 'оценок'])}
        </span>
      </div>

      {data.ratings_total === 0 ? (
        <p className="mt-3 text-[13px]" style={{ color: 'var(--muted)' }}>
          Клиенты ещё не оценивали работу
        </p>
      ) : (
        <>
          <div className="mt-3 flex flex-col gap-1.5">
            {[5, 4, 3, 2, 1].map((score) => {
              const count = data.ratings[String(score)] ?? 0
              const share = Math.round((count / data.ratings_total) * 100)
              const weak = score <= 2 && count > 0
              return (
                <div key={score} className="flex items-center gap-2">
                  <span className="num w-3 text-[12px]" style={{ color: 'var(--muted)' }}>
                    {score}
                  </span>
                  <span
                    className="flex-1 h-[18px] rounded overflow-hidden"
                    style={{ background: 'var(--panel)' }}
                  >
                    <span
                      className="block h-full rounded"
                      style={{
                        width: `${Math.max(count ? 3 : 0, (count / peak) * 100)}%`,
                        background: weak ? 'var(--alarm)' : 'var(--ink)',
                      }}
                    />
                  </span>
                  <span className="num w-14 text-right text-[12px]" style={{ color: 'var(--muted)' }}>
                    {count} · {share}%
                  </span>
                </div>
              )
            })}
          </div>

          {low > 0 && (
            <p className="mt-3 text-[12px]" style={{ color: 'var(--alarm)' }}>
              {low} {plural(low, ['низкая оценка', 'низкие оценки', 'низких оценок'])} — стоит
              посмотреть эти обращения
            </p>
          )}
        </>
      )}
    </Panel>
  )
}

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
    <div className="h-full scroll px-4 py-4 safe-t">
      <h1 className="text-[15px] font-semibold mb-3">Статистика</h1>

      {error && (
        <p className="text-[13px]" style={{ color: 'var(--alarm)' }}>
          {error}
        </p>
      )}

      {data && (
        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3 max-w-4xl">
          <Metric
            label="Обращений за сутки"
            value={String(data.day)}
            hint={`За неделю ${data.week}`}
          />
          <Metric
            label="Сейчас в работе"
            value={String(data.open_now)}
            hint={data.open_now === 0 ? 'Очередь пуста' : 'Ждут ответа'}
          />
          <Metric
            label="Среднее время первого ответа"
            value={duration(data.avg_first_reply_seconds)}
            hint="За всё время"
          />
          <Metric
            label="Средняя оценка"
            value={data.avg_rating === null ? '—' : data.avg_rating.toFixed(2)}
            hint="Из пяти"
          />
          <div className="sm:col-span-2">
            <Ratings data={data} />
          </div>
        </div>
      )}
    </div>
  )
}
