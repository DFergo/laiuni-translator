import type { JobState, Language } from '../types'
import { useT, type Key } from '../i18n'
import { Card } from './ui'
import { Banner } from './Banner'

function fmtEstimate(s?: number): string {
  if (!s || s <= 0) return '—'
  if (s < 90) return `~${s}s`
  return `~${Math.round(s / 60)} min`
}

function fmtRunAt(epoch?: number): string {
  if (!epoch) return ''
  return new Date(epoch * 1000).toLocaleString()
}

const LABEL_KEY: Record<string, Key> = {
  queued: 'status.queued', scheduled: 'status.scheduledLabel', running: 'status.running',
  done: 'status.done', failed: 'status.failed', pending: 'status.pending',
}

export function StatusView({ job, languages }: { job: JobState; languages: Language[] }) {
  const t = useT()
  const p = job.progress
  const pct = p && p.total ? Math.round((p.done / p.total) * 100) : 0
  const nameOf = (c: string) => languages.find((l) => l.code === c)?.name ?? c
  const scheduledFuture = job.status === 'scheduled' && job.run_at && job.run_at * 1000 > Date.now()
  const label = LABEL_KEY[job.status] ? t(LABEL_KEY[job.status]) : job.status

  return (
    <Card>
      <h1 className="mb-1 text-[1.5rem] font-semibold text-primary">{t('status.title')}</h1>
      <p className="mb-5 text-sm text-text-secondary">{t('status.intro')}</p>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-text-primary">{label}</span>
          <span className="text-[0.8125rem] text-text-secondary">{t('status.estimated', { t: fmtEstimate(job.estimate_s) })}</span>
        </div>

        {p && (
          <div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-bg">
              <div
                className={`h-full rounded-full transition-all ${job.status === 'done' ? 'bg-secondary' : 'bg-accent'}`}
                style={{ width: `${job.status === 'done' ? 100 : pct}%` }}
              />
            </div>
            <p className="mt-1 text-[0.8125rem] text-text-secondary">{t('status.progress', { done: p.done, total: p.total })}</p>
            {p.langs_done.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {p.langs_done.map((c) => (
                  <span key={c} className="rounded-sm border border-secondary px-2 py-0.5 text-[0.8125rem] text-secondary">
                    {nameOf(c)}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {scheduledFuture && (
          <Banner kind="info">{t('status.scheduledAt', { time: fmtRunAt(job.run_at) })}</Banner>
        )}
        {job.status === 'failed' && (
          <Banner kind="danger">{t('status.failed')}</Banner>
        )}
      </div>
    </Card>
  )
}
