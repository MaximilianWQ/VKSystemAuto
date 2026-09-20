import { motion } from 'motion/react'

type Tone = 'good' | 'warn' | 'calm' | 'plain'

const GRADIENTS: Record<Tone, string> = {
  good: 'linear-gradient(145deg, #6FCF62 0%, #A8E86B 55%, #C8F169 100%)',
  warn: 'linear-gradient(145deg, #FFA24A 0%, #FF854A 55%, #FF6B4A 100%)',
  calm: 'linear-gradient(145deg, #B9A7FF 0%, #A6BEFF 55%, #8EC5FF 100%)',
  plain: '',
}

export function StatTile({
  label,
  value,
  hint,
  tone = 'plain',
  delay = 0,
}: {
  label: string
  value: string
  hint?: string
  tone?: Tone
  delay?: number
}) {
  const filled = tone !== 'plain'
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 380, damping: 32, delay }}
      className="card relative overflow-hidden p-6 min-h-[168px] flex flex-col justify-between"
      style={filled ? { background: GRADIENTS[tone] } : undefined}
    >
      <span
        className="text-[13px] font-medium"
        style={{ color: filled ? 'rgba(0,0,0,.55)' : 'var(--muted)' }}
      >
        {label}
      </span>
      <div>
        <div
          className="numeral text-[46px]"
          style={{ color: filled ? 'rgba(0,0,0,.82)' : 'var(--ink)' }}
        >
          {value}
        </div>
        {hint && (
          <div
            className="mt-1 text-[13px]"
            style={{ color: filled ? 'rgba(0,0,0,.5)' : 'var(--muted)' }}
          >
            {hint}
          </div>
        )}
      </div>
    </motion.div>
  )
}
