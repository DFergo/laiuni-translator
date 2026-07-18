import { useState, useEffect } from 'react'
import { getFrontendConfig, updateFrontendConfig, exportFrontend, importFrontend, importFrontendFolder } from './api'

// The 17 app/UI languages (matches core/languages.py).
const LANGS: [string, string][] = [
  ['en', 'English'], ['ar', 'Arabic'], ['de', 'German'], ['es', 'Spanish'], ['fr', 'French'],
  ['hi', 'Hindi'], ['hr', 'Croatian'], ['id', 'Indonesian'], ['it', 'Italian'], ['ja', 'Japanese'],
  ['ne', 'Nepali'], ['nl', 'Dutch'], ['pl', 'Polish'], ['pt', 'Portuguese'], ['sv', 'Swedish'],
  ['th', 'Thai'], ['ur', 'Urdu'],
]

const inputCls = 'w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none'

interface Cfg {
  configured: boolean
  app_language: string
  auth_mode: 'token' | 'email-only'
  schedule_window_start_hour?: number | null
  schedule_window_duration_hours?: number | null
  allow_user_schedule_choice?: boolean | null
  schedule_default_immediate?: boolean | null
}

// tri-state select value <-> nullable boolean ('' = use global)
const boolToSel = (v: boolean | null | undefined) => (v == null ? '' : v ? 'yes' : 'no')
const selToBool = (s: string): boolean | null => (s === '' ? null : s === 'yes')
const numOrNull = (s: string): number | null => (s.trim() === '' ? null : Number(s))

export default function FrontendConfigPanel({ frontendId }: { frontendId: string }) {
  const [config, setConfig] = useState<Cfg | null>(null)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [folderPath, setFolderPath] = useState('')
  const [portMsg, setPortMsg] = useState('')

  const reload = () => getFrontendConfig(frontendId).then(({ config }) => setConfig(config as Cfg)).catch(() => {})
  useEffect(() => { reload() }, [frontendId])

  const handleImportZip = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; e.target.value = ''
    if (!file) return
    setPortMsg('Importing…')
    try { await importFrontend(frontendId, file); reload(); setPortMsg('Imported (config pushed)') }
    catch (err) { setPortMsg(err instanceof Error ? err.message : 'Import failed') }
  }
  const handleImportFolder = async () => {
    if (!folderPath.trim()) return
    setPortMsg('Importing…')
    try { await importFrontendFolder(frontendId, folderPath.trim()); reload(); setPortMsg('Imported from folder') }
    catch (err) { setPortMsg(err instanceof Error ? err.message : 'Import failed') }
  }

  if (!config) return <p className="text-xs text-gray-400 mt-3">Loading config…</p>
  const set = (patch: Partial<Cfg>) => setConfig({ ...config, ...patch })

  const save = async () => {
    setSaving(true); setMsg('')
    try {
      const { config: saved } = await updateFrontendConfig(frontendId, { ...config, configured: true })
      setConfig(saved as Cfg)
      setMsg('Saved and pushed'); setTimeout(() => setMsg(''), 3000)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Save failed')
    } finally { setSaving(false) }
  }

  return (
    <div className="mt-4 pt-4 border-t border-gray-200 space-y-5">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">App language (override)</label>
          <select value={config.app_language} onChange={e => set({ app_language: e.target.value })} className={inputCls}>
            <option value="">— use the global default —</option>
            {LANGS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </select>
          <p className="text-xs text-gray-400 mt-1">The portal UI language for this frontend (hardcoded i18n). Branding (name / colour / logo) is set above.</p>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Authentication</label>
          <select value={config.auth_mode} onChange={e => set({ auth_mode: e.target.value as Cfg['auth_mode'] })} className={inputCls}>
            <option value="token">Token — email a one-time code (default)</option>
            <option value="email-only">Email only — registered email is enough</option>
          </select>
          <p className="text-xs text-gray-400 mt-1">A registered (whitelisted) email is always required. “Email only” skips the code — for trusted private-network deploys with no external DNS.</p>
        </div>
      </div>

      {/* Scheduling (per-frontend override) */}
      <div className="pt-3 border-t border-gray-100">
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Scheduling (override)</div>
        <p className="text-xs text-gray-400 mb-2">Leave blank / “Use global” to inherit the global Settings. These override them for this frontend only.</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Window start hour (0–23)</label>
            <input type="number" min={0} max={23} value={config.schedule_window_start_hour ?? ''}
              onChange={e => set({ schedule_window_start_hour: numOrNull(e.target.value) })}
              placeholder="global" className={inputCls} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Window duration (hours)</label>
            <input type="number" min={1} max={24} value={config.schedule_window_duration_hours ?? ''}
              onChange={e => set({ schedule_window_duration_hours: numOrNull(e.target.value) })}
              placeholder="global" className={inputCls} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Let users choose immediate/scheduled</label>
            <select value={boolToSel(config.allow_user_schedule_choice)}
              onChange={e => set({ allow_user_schedule_choice: selToBool(e.target.value) })} className={inputCls}>
              <option value="">— use global —</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Default when not chosen</label>
            <select value={boolToSel(config.schedule_default_immediate)}
              onChange={e => set({ schedule_default_immediate: selToBool(e.target.value) })} className={inputCls}>
              <option value="">— use global —</option>
              <option value="yes">Immediate</option>
              <option value="no">Scheduled (at window start)</option>
            </select>
          </div>
        </div>
      </div>

      {/* Export / Import (portability) */}
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
        <p className="text-xs text-gray-400 mt-1">Import overwrites this frontend's config / branding / prompts / glossary.</p>
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
