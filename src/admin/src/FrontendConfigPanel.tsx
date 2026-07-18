import { useState, useEffect } from 'react'
import { getFrontendConfig, updateFrontendConfig, exportFrontend, importFrontend, importFrontendFolder, type FrontendConfig } from './api'

// The four wired profiles and their wired mode sets (display-only names are overridable).
const PROFILES = ['worker', 'representative', 'organizer', 'officer'] as const
const WIRED_MODES: Record<string, string[]> = {
  organizer: ['documentation', 'interview', 'advisory', 'submit'],
  officer: ['documentation', 'interview', 'advisory', 'submit', 'training'],
}

// Fixed language set (code + English name), shown alphabetically by English name.
const LANGS: { code: string; name: string }[] = [
  { code: 'ar', name: 'Arabic' }, { code: 'bn', name: 'Bengali' }, { code: 'zh', name: 'Chinese (Simplified)' },
  { code: 'hr', name: 'Croatian' }, { code: 'nl', name: 'Dutch' }, { code: 'en', name: 'English' },
  { code: 'fr', name: 'French' }, { code: 'de', name: 'German' }, { code: 'el', name: 'Greek' },
  { code: 'hi', name: 'Hindi' }, { code: 'hu', name: 'Hungarian' }, { code: 'id', name: 'Indonesian' },
  { code: 'it', name: 'Italian' }, { code: 'ja', name: 'Japanese' }, { code: 'ko', name: 'Korean' },
  { code: 'mr', name: 'Marathi' }, { code: 'pl', name: 'Polish' }, { code: 'pt', name: 'Portuguese' },
  { code: 'ro', name: 'Romanian' }, { code: 'ru', name: 'Russian' }, { code: 'es', name: 'Spanish' },
  { code: 'sw', name: 'Swahili' }, { code: 'sv', name: 'Swedish' }, { code: 'ta', name: 'Tamil' },
  { code: 'te', name: 'Telugu' }, { code: 'th', name: 'Thai' }, { code: 'tr', name: 'Turkish' },
  { code: 'uk', name: 'Ukrainian' }, { code: 'ur', name: 'Urdu' }, { code: 'vi', name: 'Vietnamese' },
  { code: 'xh', name: 'Xhosa' },
].sort((a, b) => a.name.localeCompare(b.name))

const inputCls = 'w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none'

function Toggle({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <div className={`relative w-10 h-5 rounded-full transition-colors flex-shrink-0 cursor-pointer ${on ? 'bg-uni-blue' : 'bg-gray-300'}`} onClick={onClick}>
      <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${on ? 'translate-x-5' : 'translate-x-0.5'}`} />
    </div>
  )
}

export default function FrontendConfigPanel({ frontendId }: { frontendId: string }) {
  const [config, setConfig] = useState<FrontendConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [folderPath, setFolderPath] = useState('')
  const [portMsg, setPortMsg] = useState('')

  const reload = () => getFrontendConfig(frontendId).then(({ config }) => setConfig(config)).catch(() => {})

  const handleImportZip = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setPortMsg('Importing…')
    try { await importFrontend(frontendId, file); reload(); setPortMsg('Imported (RAG reindexed, config pushed)') }
    catch (err) { setPortMsg(err instanceof Error ? err.message : 'Import failed') }
  }

  const handleImportFolder = async () => {
    if (!folderPath.trim()) return
    setPortMsg('Importing…')
    try { await importFrontendFolder(frontendId, folderPath.trim()); reload(); setPortMsg('Imported from folder') }
    catch (err) { setPortMsg(err instanceof Error ? err.message : 'Import failed') }
  }

  useEffect(() => {
    getFrontendConfig(frontendId).then(({ config }) => setConfig(config)).catch(() => {})
  }, [frontendId])

  if (!config) return <p className="text-xs text-gray-400 mt-3">Loading config…</p>

  const set = (patch: Partial<FrontendConfig>) => setConfig({ ...config, ...patch })

  const toggleProfile = (p: string) => {
    const has = config.profiles.includes(p)
    const profiles = has ? config.profiles.filter(x => x !== p) : [...config.profiles, p]
    set({ profiles })
  }

  const setAuth = (p: string, v: boolean) => set({ auth: { ...config.auth, [p]: v } })
  const setProfileName = (p: string, v: string) => set({ display_names: { ...config.display_names, profiles: { ...config.display_names.profiles, [p]: v } } })
  const setModeName = (m: string, v: string) => set({ display_names: { ...config.display_names, modes: { ...config.display_names.modes, [m]: v } } })

  const activeModes = (p: string): string[] => {
    const configured = config.modes[p]
    return (configured && configured.length > 0) ? configured : WIRED_MODES[p]
  }

  const toggleMode = (p: string, m: string) => {
    const cur = activeModes(p)
    const has = cur.includes(m)
    if (has && cur.length <= 1) return  // cannot deactivate the last mode
    const next = has ? cur.filter(x => x !== m) : WIRED_MODES[p].filter(x => cur.includes(x) || x === m)
    set({ modes: { ...config.modes, [p]: next } })
  }

  const toggleLang = (code: string) => {
    const has = config.languages.includes(code)
    set({ languages: has ? config.languages.filter(c => c !== code) : [...config.languages, code] })
  }

  const save = async () => {
    setSaving(true); setMsg('')
    try {
      const { config: saved } = await updateFrontendConfig(frontendId, { ...config, configured: true })
      setConfig(saved)
      setMsg('Saved and pushed'); setTimeout(() => setMsg(''), 3000)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Save failed')
    } finally { setSaving(false) }
  }

  return (
    <div className="mt-4 pt-4 border-t border-gray-200 space-y-5">
      {/* Profiles */}
      <div>
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Profiles shown</div>
        <div className="flex flex-wrap gap-2">
          {PROFILES.map(p => (
            <button key={p} type="button" onClick={() => toggleProfile(p)}
              className={`px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors ${config.profiles.includes(p) ? 'bg-uni-blue text-white border-uni-blue' : 'border-gray-300 text-gray-600 hover:border-uni-blue'}`}>
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Per selected profile */}
      {config.profiles.map(p => (
        <div key={p} className="border border-gray-200 rounded-lg p-3 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-gray-800 capitalize">{p}</span>
            <label className="flex items-center gap-2 text-xs text-gray-600">
              Require email auth
              <Toggle on={!!config.auth[p]} onClick={() => setAuth(p, !config.auth[p])} />
            </label>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Display name (optional)</label>
            <input value={config.display_names.profiles[p] || ''} onChange={e => setProfileName(p, e.target.value)}
              placeholder={`default: ${p}`} className={inputCls} />
          </div>
          {WIRED_MODES[p] && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Active modes (at least one)</label>
              <div className="space-y-2">
                {WIRED_MODES[p].map(m => {
                  const on = activeModes(p).includes(m)
                  return (
                    <div key={m} className="flex items-center gap-2">
                      <input type="checkbox" checked={on} onChange={() => toggleMode(p, m)} className="accent-uni-blue" />
                      <span className="text-xs text-gray-600 w-24 capitalize">{m}</span>
                      <input value={config.display_names.modes[m] || ''} onChange={e => setModeName(m, e.target.value)}
                        placeholder={`rename ${m}`} className={`${inputCls} flex-1`} />
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      ))}

      {/* Languages */}
      <div>
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Languages</div>
        <p className="text-xs text-gray-400 mb-2">Select the subset shown on this frontend. None selected = all languages.</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
          {LANGS.map(l => (
            <label key={l.code} className="flex items-center gap-2 text-xs text-gray-600">
              <input type="checkbox" checked={config.languages.includes(l.code)} onChange={() => toggleLang(l.code)} className="accent-uni-blue" />
              {l.name}
            </label>
          ))}
        </div>
      </div>

      {/* Disclaimer + data protection */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="flex items-center gap-3 text-sm text-gray-700">
          <Toggle on={config.disclaimer_enabled} onClick={() => set({ disclaimer_enabled: !config.disclaimer_enabled })} />
          Show disclaimer page
        </label>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Data protection email</label>
          <input value={config.data_protection_email || ''} onChange={e => set({ data_protection_email: e.target.value })}
            placeholder="blank = use the global SMTP data-protection email" className={inputCls} />
        </div>
      </div>

      {/* Export / import (Sprint 24) */}
      <div className="pt-3 border-t border-gray-100">
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Export / Import</div>
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={() => exportFrontend(frontendId, frontendId)}
            className="border border-gray-300 text-gray-600 rounded-lg px-3 py-1.5 text-xs font-medium hover:bg-gray-50">Export ZIP</button>
          <label className="border border-gray-300 text-gray-600 rounded-lg px-3 py-1.5 text-xs font-medium hover:bg-gray-50 cursor-pointer">
            Import ZIP
            <input type="file" accept=".zip" className="hidden" onChange={handleImportZip} />
          </label>
          <input value={folderPath} onChange={e => setFolderPath(e.target.value)}
            placeholder="/path/to/campaign folder (bind-mount)" className={`${inputCls} flex-1 min-w-[12rem]`} />
          <button onClick={handleImportFolder} disabled={!folderPath.trim()}
            className="border border-gray-300 text-gray-600 rounded-lg px-3 py-1.5 text-xs font-medium hover:bg-gray-50 disabled:opacity-50">Import folder</button>
        </div>
        <p className="text-xs text-gray-400 mt-1">RAG indexes aren't shipped — they're rebuilt on import. Import overwrites this frontend's config/branding/prompts/RAG source.</p>
        {portMsg && <p className="text-xs text-gray-600 mt-1">{portMsg}</p>}
      </div>

      <div className="flex items-center gap-3">
        <button onClick={save} disabled={saving}
          className="bg-uni-blue text-white rounded-lg px-4 py-1.5 text-sm font-medium hover:opacity-90 disabled:opacity-50">
          {saving ? 'Saving…' : 'Save & activate'}
        </button>
        {config.configured && <span className="text-xs text-gray-400">configured</span>}
        {msg && <span className="text-xs text-green-600">{msg}</span>}
      </div>
    </div>
  )
}
