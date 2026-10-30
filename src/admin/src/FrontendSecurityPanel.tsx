import { useState } from 'react'
import { updateFrontend, type Frontend, type FrontendAuthMode, type FrontendCredentials } from './api'

// 32 random bytes as hex (64 chars) — must also be set as TRANSLATOR_BACKEND_SECRET on the frontend.
export function generateSecret(): string {
  const bytes = new Uint8Array(32)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
}

// "Name: value" per line → object. Blank lines ignored.
export function parseHeaders(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const line of text.split('\n')) {
    const i = line.indexOf(':')
    if (i <= 0) continue
    const name = line.slice(0, i).trim()
    const value = line.slice(i + 1).trim()
    if (name && value) out[name] = value
  }
  return out
}

const inputCls = 'w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none'

const MODE_LABEL: Record<FrontendAuthMode, string> = {
  signed: 'Signed (recommended)',
  unsigned: 'Trusted network — unsigned',
  legacy: 'Legacy — old frontend image',
}

const MODE_HELP: Record<FrontendAuthMode, string> = {
  signed: 'Every request is signed. Uses the installation secret (TRANSLATOR_FRONTEND_SECRET) unless you set one for this frontend.',
  unsigned: 'No signature. Anyone who can reach this frontend’s backend port can read queued requests and uploaded documents and push content. Only for a private network where nothing but this backend reaches it. The frontend must run with BACKEND_SURFACE_AUTH=trusted-network.',
  legacy: 'Old protocol for frontends still on the image from before the two-port split. Unsigned; migrate when the frontend is updated.',
}

export interface AccessDraft { mode: FrontendAuthMode; secret: string; headers: string }

// Mode + optional own secret + optional extra headers. Shared by register form and Security panel.
export function AccessFields({ draft, setDraft, globalSecret, secretHint }: {
  draft: AccessDraft
  setDraft: (d: AccessDraft) => void
  globalSecret: boolean
  secretHint?: string
}) {
  const set = (k: keyof AccessDraft, v: string) => setDraft({ ...draft, [k]: v })
  const needsSecret = draft.mode === 'signed' && !globalSecret && !draft.secret.trim()
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Backend access</label>
          <select value={draft.mode} onChange={e => set('mode', e.target.value)} className={inputCls}>
            {(Object.keys(MODE_LABEL) as FrontendAuthMode[]).map(m => <option key={m} value={m}>{MODE_LABEL[m]}</option>)}
          </select>
        </div>
        {draft.mode === 'signed' && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Own secret (optional)</label>
            <div className="flex gap-2">
              <input type="text" value={draft.secret} onChange={e => set('secret', e.target.value)}
                placeholder={secretHint ?? (globalSecret ? 'Blank = installation secret' : 'Required: no installation secret set')}
                className={`${inputCls} font-mono`} autoComplete="off" spellCheck={false} />
              <button type="button" onClick={() => set('secret', generateSecret())}
                className="text-xs px-3 py-1 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 font-medium whitespace-nowrap">
                Generate
              </button>
            </div>
          </div>
        )}
      </div>
      <p className={`text-xs ${draft.mode === 'unsigned' ? 'text-amber-700' : 'text-gray-400'}`}>{MODE_HELP[draft.mode]}</p>
      {needsSecret && (
        <p className="text-xs text-uni-red">No installation secret on this backend (TRANSLATOR_FRONTEND_SECRET). Enter a secret for this frontend, or set the variable and restart the backend.</p>
      )}
      <details className="text-sm" open={!!draft.headers}>
        <summary className="cursor-pointer text-xs text-gray-500 select-none">Extra headers (optional, e.g. Cloudflare Access service token)</summary>
        <textarea value={draft.headers} onChange={e => set('headers', e.target.value)} rows={2}
          placeholder={'CF-Access-Client-Id: …\nCF-Access-Client-Secret: …'}
          className={`${inputCls} font-mono mt-2`} spellCheck={false} />
        <p className="text-xs text-gray-400 mt-1">One "Name: value" per line. Write-only: never shown again.</p>
      </details>
    </div>
  )
}

// Translator: the address users reach (tunnel/domain), used in emailed download links.
export function PublicUrlField({ value, onChange, mode }: { value: string; onChange: (v: string) => void; mode: FrontendAuthMode }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">Public address (emailed links)</label>
      <input type="text" value={value} onChange={e => onChange(e.target.value)} spellCheck={false}
        placeholder="e.g. https://translate.example.org — blank = the URL above"
        className={`${inputCls} font-mono`} />
      {mode !== 'legacy' && !value.trim() && (
        <p className="text-xs text-amber-700 mt-1">Without it, emailed download links point to the backend port, which users cannot open.</p>
      )}
    </div>
  )
}

export function draftToCredentials(d: AccessDraft): FrontendCredentials {
  const out: FrontendCredentials = { auth_mode: d.mode }
  if (d.mode === 'signed' && d.secret.trim()) out.signing_secret = d.secret.trim()
  const headers = parseHeaders(d.headers)
  if (Object.keys(headers).length) out.extra_headers = headers
  return out
}

export function SigningBadge({ f }: { f: Frontend }) {
  const base = 'ml-2 text-[10px] px-1.5 py-0.5 rounded border'
  const mode = f.auth_mode ?? (f.signing_enabled ? 'signed' : 'legacy')
  return (
    <>
      {mode === 'signed' && (f.signing_enabled
        ? <span className={`${base} bg-green-50 text-green-700 border-green-200`}>signed{f.signing_source === 'own' ? ' · own secret' : ''}</span>
        : <span className={`${base} bg-red-50 text-uni-red border-red-200`} title="No secret available">signed · no secret</span>)}
      {mode === 'unsigned' && <span className={`${base} bg-amber-50 text-amber-700 border-amber-200`} title="Requests to this frontend are not signed">trusted network · unsigned</span>}
      {mode === 'legacy' && <span className={`${base} bg-gray-50 text-gray-500 border-gray-200`} title="Old frontend image, unsigned protocol">legacy</span>}
      {mode === 'signed' && f.surface_auth === 'trusted-network' && (
        <span className={`${base} bg-amber-50 text-amber-700 border-amber-200`} title="The frontend runs with BACKEND_SURFACE_AUTH=trusted-network and does not check signatures">frontend accepts unsigned</span>
      )}
    </>
  )
}

export default function FrontendSecurityPanel({ f, globalSecret, onSaved }: { f: Frontend; globalSecret: boolean; onSaved: () => void }) {
  const [url, setUrl] = useState(f.url)
  const [publicUrl, setPublicUrl] = useState(f.public_url ?? '')
  const [draft, setDraft] = useState<AccessDraft>({ mode: f.auth_mode ?? 'legacy', secret: '', headers: '' })
  const [clearOwn, setClearOwn] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  const save = async (data: FrontendCredentials & { url?: string; public_url?: string }, done: string) => {
    setBusy(true); setErr(''); setMsg('')
    try {
      await updateFrontend(f.id, data)
      setDraft(d => ({ ...d, secret: '', headers: '' }))
      setClearOwn(false)
      setMsg(done)
      onSaved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Update failed')
    } finally {
      setBusy(false)
    }
  }

  const urlChanged = url.trim().replace(/\/+$/, '') !== f.url
  const publicChanged = publicUrl.trim().replace(/\/+$/, '') !== (f.public_url ?? '')
  const modeChanged = draft.mode !== (f.auth_mode ?? 'legacy')
  const dirty = urlChanged || publicChanged || modeChanged || !!draft.secret.trim() || !!draft.headers.trim() || clearOwn

  // URL + mode + credentials go in ONE update, verified against the frontend with the final combination.
  const saveAll = () => {
    const data: FrontendCredentials & { url?: string; public_url?: string } = draftToCredentials(draft)
    if (urlChanged) data.url = url.trim()
    if (publicChanged) data.public_url = publicUrl.trim()
    if (clearOwn && !draft.secret.trim()) data.signing_secret = ''
    save(data, 'Saved — the frontend accepted the new settings.')
  }

  return (
    <div className="mt-3 border-t border-gray-100 pt-3 space-y-3">
      <div className="text-xs text-gray-500">
        Current: <strong>{MODE_LABEL[f.auth_mode ?? 'legacy']}</strong>
        {f.auth_mode === 'signed' && <> · secret: <strong>{f.signing_source === 'own' ? 'own' : f.signing_source === 'global' ? 'installation' : 'none'}</strong></>}
        {' · '}extra headers: <strong>{f.extra_header_names?.length ? f.extra_header_names.join(', ') : 'none'}</strong>
      </div>
      {f.auth_mode === 'signed' && f.surface_auth === 'trusted-network' && (
        <p className="text-xs text-amber-700">This frontend reports BACKEND_SURFACE_AUTH=trusted-network: it does not check signatures, so signing here adds no protection until that is changed.</p>
      )}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Backend-port URL</label>
        <input type="text" value={url} onChange={e => setUrl(e.target.value)} spellCheck={false} className={`${inputCls} font-mono`} />
      </div>
      <PublicUrlField value={publicUrl} onChange={setPublicUrl} mode={draft.mode} />
      <AccessFields draft={draft} setDraft={setDraft} globalSecret={globalSecret}
        secretHint={f.signing_source === 'own' ? 'Blank = keep the current own secret' : undefined} />
      {f.signing_source === 'own' && draft.mode === 'signed' && (
        <label className="flex items-center gap-2 text-xs text-gray-600">
          <input type="checkbox" checked={clearOwn} onChange={e => setClearOwn(e.target.checked)} />
          Remove the own secret and use the installation secret
        </label>
      )}
      <div className="flex gap-2">
        <button onClick={saveAll} disabled={busy || !dirty}
          className="bg-uni-blue text-white rounded-lg px-4 py-1.5 text-sm font-medium hover:opacity-90 disabled:opacity-50">
          {busy ? '...' : 'Save'}
        </button>
        {!!f.extra_header_names?.length && (
          <button onClick={() => save({ extra_headers: {} }, 'Extra headers removed.')} disabled={busy}
            className="text-xs px-3 py-1 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 font-medium">
            Remove extra headers
          </button>
        )}
      </div>
      <p className="text-xs text-gray-400">
        Rotating a secret without downtime: put the new value in TRANSLATOR_BACKEND_SECRET on the frontend and the old one in
        TRANSLATOR_BACKEND_SECRET_PREVIOUS, save it here (or change TRANSLATOR_FRONTEND_SECRET on the backend), then remove the previous one.
      </p>
      {msg && <p className="text-xs text-green-700">{msg}</p>}
      {err && <p className="text-xs text-uni-red">{err}</p>}
    </div>
  )
}
