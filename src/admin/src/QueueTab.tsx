import { useEffect, useState, useCallback } from 'react'
import {
  getQueue, prioritiseJob, moveJob, retryJob, deleteQueueJob, cancelQueueJob, getUsage,
  type QueueJob, type FailedJob, type UsageRow,
} from './api'

export default function QueueTab() {
  const [jobs, setJobs] = useState<QueueJob[]>([])
  const [failed, setFailed] = useState<FailedJob[]>([])
  const [usage, setUsage] = useState<UsageRow[]>([])
  const [error, setError] = useState('')
  const [copiedId, setCopiedId] = useState('')

  const refresh = useCallback(async () => {
    try {
      const [q, u] = await Promise.all([getQueue(), getUsage()])
      setJobs(q.jobs); setFailed(q.failed); setUsage(u.usage)
    } catch (e) { setError(e instanceof Error ? e.message : 'Failed to load') }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 3000)
    return () => clearInterval(id)
  }, [refresh])

  const act = async (fn: () => Promise<unknown>) => { try { await fn(); await refresh() } catch { /* ignore */ } }

  const copyError = async (j: FailedJob) => {
    try { await navigator.clipboard.writeText(j.error || '(no error recorded)') } catch { /* ignore */ }
    setCopiedId(j.id); setTimeout(() => setCopiedId(''), 1500)
  }

  const relaunch = async (id: string) => {
    const r = await retryJob(id)
    if (!r.ok) { alert('Could not relaunch — the source file is no longer on disk.'); return }
    await refresh()
  }

  const statusBadge = (s: string) => {
    const c = s === 'running' ? 'bg-green-100 text-green-700'
      : s === 'scheduled' ? 'bg-yellow-100 text-yellow-700' : 'bg-gray-100 text-gray-600'
    return <span className={`text-xs px-2 py-0.5 rounded-full ${c}`}>{s}</span>
  }

  return (
    <div className="space-y-6">
      {/* Queue */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-lg font-semibold text-gray-900">Processing queue</h2>
          <button onClick={refresh} className="text-xs border border-gray-300 rounded-lg px-3 py-1.5 hover:bg-gray-50">Refresh</button>
        </div>
        <p className="text-sm text-gray-500 mb-4">Jobs run one at a time in this order (running first, then priority, then request time). Scheduled jobs wait for the window.</p>
        {error && <div className="bg-red-50 border border-red-200 text-uni-red text-sm rounded-lg p-2 mb-3">{error}</div>}
        <div className="overflow-x-auto border border-gray-200 rounded-lg">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['#', 'User', 'Format', 'Langs', 'Mode', 'Status', 'Progress', 'Priority', ''].map(h => (
                  <th key={h} className="px-3 py-2 text-left font-medium text-gray-700">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {jobs.length === 0 && (
                <tr><td colSpan={9} className="px-3 py-4 text-center text-gray-500">Queue is empty.</td></tr>
              )}
              {jobs.map((j) => (
                <tr key={j.id} className="border-b border-gray-100 last:border-0">
                  <td className="px-3 py-2 text-gray-500">{j.position}</td>
                  <td className="px-3 py-2">{j.owner}{j.origin === 'api' && <span className="ml-1 text-xs text-gray-400">(api)</span>}</td>
                  <td className="px-3 py-2 uppercase text-gray-500">{j.format}</td>
                  <td className="px-3 py-2">{j.n_langs}</td>
                  <td className="px-3 py-2 text-gray-500">{j.mode}</td>
                  <td className="px-3 py-2">{statusBadge(j.status)}</td>
                  <td className="px-3 py-2 min-w-[120px]">
                    {j.status === 'running' && (
                      <div title={`${j.langs_done ?? 0}/${j.n_langs} language(s) done · ${j.connection || ''}`}>
                        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                          <div className="h-full bg-uni-blue transition-all" style={{ width: `${Math.round((j.progress ?? 0) * 100)}%` }} />
                        </div>
                        <span className="text-xs text-gray-500">{Math.round((j.progress ?? 0) * 100)}%</span>
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2">{j.priority ? '★' : ''}</td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <button title="Stop this job" onClick={() => { if (confirm('Cancel this job?')) act(() => cancelQueueJob(j.id)) }} className="px-1.5 text-uni-red hover:underline">cancel</button>
                    {j.status !== 'running' && (
                      <>
                        <button title="Move up" onClick={() => act(() => moveJob(j.id, 'up'))} className="px-1.5 text-gray-500 hover:text-gray-800">↑</button>
                        <button title="Move down" onClick={() => act(() => moveJob(j.id, 'down'))} className="px-1.5 text-gray-500 hover:text-gray-800">↓</button>
                        <button title={j.priority ? 'Remove priority' : 'Prioritise'} onClick={() => act(() => prioritiseJob(j.id, !j.priority))} className="px-1.5 text-uni-blue hover:underline">{j.priority ? 'unstar' : 'star'}</button>
                        <button title="Delete" onClick={() => { if (confirm('Delete this job?')) act(() => deleteQueueJob(j.id)) }} className="px-1.5 text-uni-red hover:underline">delete</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Failed jobs */}
      {failed.length > 0 && (
        <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-1">Failed jobs</h2>
          <p className="text-sm text-gray-500 mb-4">Kept here with the recorded reason — copy it, relaunch the job (its file is still on disk), or delete it. No need to read the container logs.</p>
          <div className="space-y-3">
            {failed.map((j) => (
              <div key={j.id} className="border border-red-200 bg-red-50/40 rounded-lg p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm text-gray-700 min-w-0">
                    <span className="font-medium">{j.owner}</span>
                    <span className="text-gray-400"> · </span>
                    <span className="uppercase text-gray-500">{j.format}</span>
                    <span className="text-gray-400"> · </span>
                    <span className="text-gray-500">{j.n_langs} lang{j.n_langs === 1 ? '' : 's'}</span>
                  </div>
                  <div className="flex items-center gap-1 whitespace-nowrap">
                    <button title="Copy the failure reason" onClick={() => copyError(j)} className="text-xs border border-gray-300 rounded-lg px-2 py-1 hover:bg-white">{copiedId === j.id ? 'copied ✓' : 'copy error'}</button>
                    <button title="Relaunch this job" onClick={() => relaunch(j.id)} className="text-xs border border-uni-blue text-uni-blue rounded-lg px-2 py-1 hover:bg-white">relaunch</button>
                    <button title="Delete" onClick={() => { if (confirm('Delete this failed job?')) act(() => deleteQueueJob(j.id)) }} className="text-xs text-uni-red px-2 py-1 hover:underline">delete</button>
                  </div>
                </div>
                {j.error && (
                  <pre className="mt-2 text-xs text-gray-600 bg-white border border-gray-200 rounded p-2 max-h-32 overflow-auto whitespace-pre-wrap break-words">{j.error}</pre>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Usage log */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-1">Usage</h2>
        <p className="text-sm text-gray-500 mb-4">Per-user counts only — never filenames or content. Survives retention.</p>
        <div className="overflow-x-auto border border-gray-200 rounded-lg">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {['User', 'Documents', 'Languages', 'First', 'Last'].map(h => (
                  <th key={h} className="px-3 py-2 text-left font-medium text-gray-700">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {usage.length === 0 && (
                <tr><td colSpan={5} className="px-3 py-4 text-center text-gray-500">No usage yet.</td></tr>
              )}
              {usage.map((u) => (
                <tr key={u.email} className="border-b border-gray-100 last:border-0">
                  <td className="px-3 py-2">{u.email}</td>
                  <td className="px-3 py-2">{u.documents}</td>
                  <td className="px-3 py-2 text-gray-500">{u.languages.join(', ')}</td>
                  <td className="px-3 py-2 text-gray-500">{u.first_day}</td>
                  <td className="px-3 py-2 text-gray-500">{u.last_day}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
