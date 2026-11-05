import { useEffect, useState, useCallback } from 'react'
import { listApiTokens, createApiToken, revokeApiToken, type ApiToken } from './api'

// Machine-API tokens (SPEC §16.1). The plaintext exists only in the response to
// "create"; the backend keeps just a hash, so it is shown once and offered as a download.
export default function ApiTokensTab() {
  const [tokens, setTokens] = useState<ApiToken[]>([])
  const [name, setName] = useState('')
  const [fresh, setFresh] = useState<{ name: string; token: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try { setTokens((await listApiTokens()).tokens) }
    catch (e) { setError(e instanceof Error ? e.message : 'Failed to load') }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const create = async () => {
    setError('')
    try {
      const r = await createApiToken(name.trim())
      setFresh({ name: r.name, token: r.token }); setName(''); setCopied(false)
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not create the token') }
  }

  const revoke = async (t: ApiToken) => {
    if (!confirm(`Revoke "${t.name}"? Scripts using it will stop working immediately.`)) return
    try { await revokeApiToken(t.id); if (fresh?.name === t.name) setFresh(null); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not revoke the token') }
  }

  const download = () => {
    if (!fresh) return
    const blob = new Blob([`---start token---\n${fresh.token}\n---end token---\n`], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `${fresh.name.replace(/[^\w.-]+/g, '_') || 'api'}-token.txt`
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
  }

  const copy = async () => {
    if (!fresh) return
    try { await navigator.clipboard.writeText(fresh.token); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { /* ignore */ }
  }

  const fmt = (ts: number | null) => ts ? new Date(ts * 1000).toLocaleString() : 'never'

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-1">API tokens</h2>
        <p className="text-sm text-gray-500 mb-4">
          Tokens for scripts and skills calling <code>/api/v1</code> on this backend (send as <code>Authorization: Bearer …</code>).
          The schema is at <code>/openapi.json</code>. Only reachable where this admin is — keep it off the public internet.
        </p>
        {error && <div className="bg-red-50 border border-red-200 text-uni-red text-sm rounded-lg p-2 mb-3">{error}</div>}

        <div className="flex gap-2">
          <input
            value={name} onChange={e => setName(e.target.value)} maxLength={60}
            onKeyDown={e => { if (e.key === 'Enter' && name.trim()) create() }}
            placeholder="Token name (e.g. uni-translator-skill)"
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
          <button onClick={create} disabled={!name.trim()}
            className="bg-uni-blue text-white text-sm rounded-lg px-4 py-2 disabled:opacity-40">Generate token</button>
        </div>

        {fresh && (
          <div className="mt-4 border border-yellow-300 bg-yellow-50 rounded-lg p-4">
            <p className="text-sm font-medium text-gray-900 mb-1">Token for “{fresh.name}” — copy or download it now; it cannot be shown again.</p>
            <code className="block bg-white border border-gray-200 rounded px-3 py-2 text-xs break-all select-all">{fresh.token}</code>
            <div className="flex gap-2 mt-3">
              <button onClick={download} className="text-sm bg-uni-blue text-white rounded-lg px-3 py-1.5">Download .txt</button>
              <button onClick={copy} className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 hover:bg-white">{copied ? 'Copied' : 'Copy'}</button>
              <button onClick={() => setFresh(null)} className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 hover:bg-white ml-auto">Done</button>
            </div>
          </div>
        )}
      </div>

      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <div className="overflow-x-auto border border-gray-200 rounded-lg">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>{['Name', 'ID', 'Created', 'Last used', ''].map(h => (
                <th key={h} className="px-3 py-2 text-left font-medium text-gray-700">{h}</th>))}</tr>
            </thead>
            <tbody>
              {tokens.length === 0 && <tr><td colSpan={5} className="px-3 py-4 text-center text-gray-500">No API tokens.</td></tr>}
              {tokens.map(t => (
                <tr key={t.id} className="border-b border-gray-100 last:border-0">
                  <td className="px-3 py-2 font-medium">{t.name}</td>
                  <td className="px-3 py-2 font-mono text-xs text-gray-500">{t.id}</td>
                  <td className="px-3 py-2">{fmt(t.created_at)}</td>
                  <td className="px-3 py-2">{fmt(t.last_used)}</td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => revoke(t)} className="text-xs border border-red-300 text-uni-red rounded-lg px-2 py-1 hover:bg-red-50">Revoke</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
