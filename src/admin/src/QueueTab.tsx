import { useEffect, useState, useCallback } from 'react'
import {
  getQueue, prioritiseJob, moveJob, deleteQueueJob, getUsage,
  type QueueJob, type UsageRow,
} from './api'

export default function QueueTab() {
  const [jobs, setJobs] = useState<QueueJob[]>([])
  const [usage, setUsage] = useState<UsageRow[]>([])
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const [q, u] = await Promise.all([getQueue(), getUsage()])
      setJobs(q.jobs); setUsage(u.usage)
    } catch (e) { setError(e instanceof Error ? e.message : 'Failed to load') }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 3000)
    return () => clearInterval(id)
  }, [refresh])

  const act = async (fn: () => Promise<unknown>) => { try { await fn(); await refresh() } catch { /* ignore */ } }

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
                {['#', 'User', 'Format', 'Langs', 'Mode', 'Status', 'Priority', ''].map(h => (
                  <th key={h} className="px-3 py-2 text-left font-medium text-gray-700">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {jobs.length === 0 && (
                <tr><td colSpan={8} className="px-3 py-4 text-center text-gray-500">Queue is empty.</td></tr>
              )}
              {jobs.map((j) => (
                <tr key={j.id} className="border-b border-gray-100 last:border-0">
                  <td className="px-3 py-2 text-gray-500">{j.position}</td>
                  <td className="px-3 py-2">{j.owner}</td>
                  <td className="px-3 py-2 uppercase text-gray-500">{j.format}</td>
                  <td className="px-3 py-2">{j.n_langs}</td>
                  <td className="px-3 py-2 text-gray-500">{j.mode}</td>
                  <td className="px-3 py-2">{statusBadge(j.status)}</td>
                  <td className="px-3 py-2">{j.priority ? '★' : ''}</td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
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
