import type { JobState, Language } from '../types'
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

const LABELS: Record<string, string> = {
  queued: 'Queued', scheduled: 'Scheduled', running: 'Translating…',
  done: 'Done', failed: 'Failed', pending: 'Submitting…',
}

export function StatusView({ job, languages }: { job: JobState; languages: Language[] }) {
  const p = job.progress
  const pct = p && p.total ? Math.round((p.done / p.total) * 100) : 0
  const nameOf = (c: string) => languages.find((l) => l.code === c)?.name ?? c
  const scheduledFuture = job.status === 'scheduled' && job.run_at && job.run_at * 1000 > Date.now()

  return (
    <Card>
      <h1 className="mb-1 text-[1.5rem] font-semibold text-primary">Your translation</h1>
      <p className="mb-5 text-sm text-text-secondary">You can leave this page — the result is emailed when ready.</p>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-text-primary">{LABELS[job.status] ?? job.status}</span>
          <span className="text-[0.8125rem] text-text-secondary">Estimated {fmtEstimate(job.estimate_s)}</span>
        </div>

        {p && (
          <div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-bg">
              <div
                className={`h-full rounded-full transition-all ${job.status === 'done' ? 'bg-secondary' : 'bg-accent'}`}
                style={{ width: `${job.status === 'done' ? 100 : pct}%` }}
              />
            </div>
            <p className="mt-1 text-[0.8125rem] text-text-secondary">{p.done} of {p.total} languages</p>
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
          <Banner kind="info">Scheduled to run at {fmtRunAt(job.run_at)}.</Banner>
        )}
        {job.status === 'failed' && (
          <Banner kind="danger">The translation failed. Please try again or contact your administrator.</Banner>
        )}
      </div>
    </Card>
  )
}
