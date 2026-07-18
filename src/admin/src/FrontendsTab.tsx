import { useState, useEffect } from 'react'
import { listFrontends, registerFrontend, updateFrontend, removeFrontend, getFrontendBranding, updateFrontendBranding, getBrandingTranslationStatus, retranslateBranding, listDeletedFrontends, restoreFrontend, exportGlobalConfig, importGlobalConfig, type Frontend, type BrandingConfig } from './api'
import FrontendConfigPanel from './FrontendConfigPanel'
import { DEFAULT_DISCLAIMER_MD, DEFAULT_INSTRUCTIONS_MD } from './brandingDefaults'

export default function FrontendsTab() {
  const [frontends, setFrontends] = useState<Frontend[]>([])
  const [newUrl, setNewUrl] = useState('')
  const [newName, setNewName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const [deleted, setDeleted] = useState<Frontend[]>([])

  const refresh = async () => {
    try {
      const { frontends: list } = await listFrontends()
      setFrontends(list)
      try {
        const { frontends: del } = await listDeletedFrontends()
        setDeleted(del)
      } catch { /* ignore */ }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load')
    }
  }

  const handleRestore = async (fid: string) => {
    await restoreFrontend(fid)
    await refresh()
  }

  const [globalMsg, setGlobalMsg] = useState('')
  const handleImportGlobal = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!confirm('Import global config? This overwrites prompts, knowledge, connections, SMTP and other global settings. Restart the backend afterwards to reload registry-backed config.')) return
    setGlobalMsg('Importing…')
    try {
      const r = await importGlobalConfig(file)
      setGlobalMsg(r.note || 'Global config imported')
    } catch (err) {
      setGlobalMsg(err instanceof Error ? err.message : 'Import failed')
    }
  }

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 10000)
    return () => clearInterval(interval)
  }, [])

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await registerFrontend(newUrl, newName)
      setNewUrl('')
      setNewName('')
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  const handleToggle = async (f: Frontend) => {
    await updateFrontend(f.id, { enabled: !f.enabled })
    await refresh()
  }

  const handleRemove = async (f: Frontend) => {
    await removeFrontend(f.id)
    await refresh()
  }

  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')

  // Branding
  const [brandingOpen, setBrandingOpen] = useState<string | null>(null)
  const [branding, setBranding] = useState<BrandingConfig | null>(null)
  const [brandingSaving, setBrandingSaving] = useState(false)
  const [brandingSuccess, setBrandingSuccess] = useState('')
  const [translationStatus, setTranslationStatus] = useState<{ status: string; progress: number; total: number } | null>(null)
  const [configOpen, setConfigOpen] = useState<string | null>(null)

  const startEdit = (f: Frontend) => {
    setEditingId(f.id)
    setEditName(f.name)
  }

  const saveEdit = async (id: string) => {
    await updateFrontend(id, { name: editName })
    setEditingId(null)
    await refresh()
  }

  const toggleBranding = async (id: string) => {
    if (brandingOpen === id) {
      setBrandingOpen(null)
      setBranding(null)
      setTranslationStatus(null)
      return
    }
    try {
      const data = await getFrontendBranding(id)
      setBranding(data)
      setBrandingOpen(id)
    } catch {
      // ignore
    }
  }

  const pollTranslation = (fid: string) => {
    const poll = setInterval(async () => {
      try {
        const s = await getBrandingTranslationStatus(fid)
        setTranslationStatus(s)
        if (s.status === 'done' || s.status === 'idle') {
          clearInterval(poll)
          setTimeout(() => setTranslationStatus(null), 5000)
        }
      } catch {
        clearInterval(poll)
      }
    }, 2000)
  }

  const handleBrandingSave = async () => {
    if (!brandingOpen || !branding) return
    setBrandingSaving(true)
    setTranslationStatus(null)
    try {
      const result = await updateFrontendBranding(brandingOpen, branding)
      setBrandingSuccess('Branding saved and pushed to frontend')
      setTimeout(() => setBrandingSuccess(''), 3000)

      // Fill-missing translation started → poll progress
      if (result.translation_status === 'translating') pollTranslation(brandingOpen)
    } catch {
      // ignore
    } finally {
      setBrandingSaving(false)
    }
  }

  const handleRetranslate = async () => {
    if (!brandingOpen) return
    setTranslationStatus(null)
    try {
      const result = await retranslateBranding(brandingOpen)
      if (result.translation_status === 'translating') pollTranslation(brandingOpen)
    } catch {
      // ignore
    }
  }

  const statusColor = (s: string) => {
    if (s === 'online') return 'bg-green-500'
    if (s === 'offline') return 'bg-red-500'
    return 'bg-gray-400'
  }

  return (
    <div className="space-y-6">
      {/* Register form */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-4">Add Frontend</h3>
        <form onSubmit={handleRegister} className="flex gap-3 items-end">
          <div className="flex-1">
            <label className="block text-sm font-medium text-gray-700 mb-1">URL</label>
            <input
              type="text"
              value={newUrl}
              onChange={e => setNewUrl(e.target.value)}
              placeholder="http://10.210.66.103:8091"
              className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none text-sm"
              required
            />
          </div>
          <div className="w-40">
            <label className="block text-sm font-medium text-gray-700 mb-1">Name (optional)</label>
            <input
              type="text"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="Worker #1"
              className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="bg-uni-blue text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors hover:opacity-90 disabled:opacity-50"
          >
            {loading ? '...' : 'Register'}
          </button>
        </form>
        {error && <p className="text-uni-red text-sm mt-2">{error}</p>}
      </div>

      {/* Frontends list */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-4">Registered Frontends</h3>
        {frontends.length === 0 ? (
          <p className="text-gray-400 text-sm">No frontends registered yet.</p>
        ) : (
          <div className="space-y-3">
            {frontends.map(f => (
              <div key={f.id} className="border border-gray-200 rounded-lg px-4 py-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`w-2.5 h-2.5 rounded-full ${statusColor(f.status)}`} />
                    <div>
                      {editingId === f.id ? (
                        <div className="flex items-center gap-2">
                          <input
                            type="text"
                            value={editName}
                            onChange={e => setEditName(e.target.value)}
                            onKeyDown={e => e.key === 'Enter' && saveEdit(f.id)}
                            className="border border-gray-300 rounded px-2 py-0.5 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
                            autoFocus
                          />
                          <button onClick={() => saveEdit(f.id)} className="text-xs text-uni-blue hover:underline">Save</button>
                          <button onClick={() => setEditingId(null)} className="text-xs text-gray-400 hover:underline">Cancel</button>
                        </div>
                      ) : (
                        <div className="text-sm font-medium text-gray-800">
                          {f.name}
                          <button onClick={() => startEdit(f)} className="ml-2 text-xs text-gray-400 hover:text-uni-blue">edit</button>
                        </div>
                      )}
                      <div className="text-xs text-gray-400">{f.url}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setConfigOpen(configOpen === f.id ? null : f.id)}
                      className="text-xs px-3 py-1 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 font-medium transition-colors"
                    >
                      {configOpen === f.id ? 'Close Config' : 'Configure'}
                    </button>
                    <button
                      onClick={() => toggleBranding(f.id)}
                      className="text-xs px-3 py-1 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 font-medium transition-colors"
                    >
                      {brandingOpen === f.id ? 'Close Branding' : 'Branding'}
                    </button>
                    <button
                      onClick={() => handleToggle(f)}
                      className={`text-xs px-3 py-1 rounded-lg border font-medium transition-colors ${
                        f.enabled
                          ? 'border-green-300 text-green-700 hover:bg-green-50'
                          : 'border-gray-300 text-gray-500 hover:bg-gray-50'
                      }`}
                    >
                      {f.enabled ? 'Enabled' : 'Disabled'}
                    </button>
                    <button
                      onClick={() => handleRemove(f)}
                      className="text-xs px-3 py-1 rounded-lg border border-uni-red text-uni-red hover:bg-red-50 font-medium transition-colors"
                    >
                      Remove
                    </button>
                  </div>
                </div>

                {/* Per-frontend config panel */}
                {configOpen === f.id && <FrontendConfigPanel frontendId={f.id} />}

                {/* Branding editor */}
                {brandingOpen === f.id && branding && (
                  <div className="mt-4 pt-4 border-t border-gray-200 space-y-3">
                    <p className="text-xs text-gray-400">Custom branding for this frontend. Leave empty to use UNI defaults.</p>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1">App Title (header)</label>
                        <input
                          type="text"
                          value={branding.app_title}
                          onChange={e => setBranding({ ...branding, app_title: e.target.value })}
                          placeholder="HRDD Helper"
                          className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1">Logo URL (optional)</label>
                        <input
                          type="text"
                          value={branding.logo_url}
                          onChange={e => setBranding({ ...branding, logo_url: e.target.value })}
                          placeholder="https://example.com/logo.png"
                          className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
                        />
                      </div>
                    </div>
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="block text-xs font-medium text-gray-600">Disclaimer page (Markdown — whole page, headings included)</label>
                        <button type="button" onClick={() => setBranding({ ...branding, disclaimer_text: DEFAULT_DISCLAIMER_MD })}
                          className="text-xs text-uni-blue hover:underline">Load default template</button>
                      </div>
                      <textarea
                        value={branding.disclaimer_text}
                        onChange={e => setBranding({ ...branding, disclaimer_text: e.target.value })}
                        rows={10}
                        placeholder="Leave empty for the default disclaimer page. Use ## for headings. [DATA_PROTECTION_EMAIL] is substituted at render time."
                        className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-xs font-mono focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
                      />
                    </div>
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="block text-xs font-medium text-gray-600">Instructions page (Markdown — whole page, overrides default for all roles)</label>
                        <button type="button" onClick={() => setBranding({ ...branding, instructions_text: DEFAULT_INSTRUCTIONS_MD })}
                          className="text-xs text-uni-blue hover:underline">Load default template</button>
                      </div>
                      <textarea
                        value={branding.instructions_text}
                        onChange={e => setBranding({ ...branding, instructions_text: e.target.value })}
                        rows={10}
                        placeholder="Leave empty for the default instructions page. Use ## for headings."
                        className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-xs font-mono focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
                      />
                    </div>
                    <div className="flex items-center gap-3">
                      <button
                        onClick={handleBrandingSave}
                        disabled={brandingSaving}
                        className="bg-uni-blue text-white rounded-lg px-4 py-1.5 text-sm font-medium hover:opacity-90 disabled:opacity-50"
                      >
                        {brandingSaving ? 'Saving...' : 'Save Branding'}
                      </button>
                      {(branding.disclaimer_text || branding.instructions_text) && (
                        <button
                          onClick={handleRetranslate}
                          disabled={brandingSaving}
                          className="border border-gray-300 text-gray-600 rounded-lg px-4 py-1.5 text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
                          title="Regenerate all languages from the current English source (overwrites existing translations)"
                        >
                          Re-translate all
                        </button>
                      )}
                      {brandingSuccess && <span className="text-xs text-green-600">{brandingSuccess}</span>}
                    </div>
                    {translationStatus && translationStatus.status === 'translating' && (
                      <div className="space-y-1">
                        <div className="flex items-center justify-between text-xs text-gray-500">
                          <span>Translating to {translationStatus.total} languages...</span>
                          <span>{translationStatus.progress}/{translationStatus.total}</span>
                        </div>
                        <div className="w-full bg-gray-200 rounded-full h-1.5">
                          <div
                            className="bg-uni-blue h-1.5 rounded-full transition-all"
                            style={{ width: `${(translationStatus.progress / translationStatus.total) * 100}%` }}
                          />
                        </div>
                      </div>
                    )}
                    {translationStatus && translationStatus.status === 'done' && (
                      <p className="text-xs text-green-600">Translations complete ({translationStatus.total} languages)</p>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Global config backup (Sprint 24) */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-1">Global Config Backup</h3>
        <p className="text-xs text-gray-400 mb-4">Export or restore the global <code>config/</code> (prompts, knowledge, connections, SMTP, …) as a ZIP. RAG indexes are rebuilt, not shipped.</p>
        <div className="flex items-center gap-2">
          <button onClick={() => exportGlobalConfig()} className="border border-gray-300 text-gray-600 rounded-lg px-3 py-1.5 text-xs font-medium hover:bg-gray-50">Export global config</button>
          <label className="border border-gray-300 text-gray-600 rounded-lg px-3 py-1.5 text-xs font-medium hover:bg-gray-50 cursor-pointer">
            Import global config
            <input type="file" accept=".zip" className="hidden" onChange={handleImportGlobal} />
          </label>
          {globalMsg && <span className="text-xs text-gray-600">{globalMsg}</span>}
        </div>
      </div>

      {/* Recently deleted (soft-delete, recoverable) */}
      {deleted.length > 0 && (
        <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-1">Recently Deleted</h3>
          <p className="text-xs text-gray-400 mb-4">Soft-deleted frontends are archived and can be restored.</p>
          <div className="space-y-2">
            {deleted.map(f => (
              <div key={f.id} className="flex items-center justify-between border border-gray-200 rounded-lg px-4 py-2">
                <div>
                  <span className="text-sm font-medium text-gray-700">{f.name}</span>
                  <span className="text-xs text-gray-400 ml-2">{f.url}</span>
                </div>
                <button
                  onClick={() => handleRestore(f.id)}
                  className="text-xs px-3 py-1 rounded-lg border border-uni-blue text-uni-blue hover:bg-blue-50 font-medium transition-colors"
                >
                  Restore
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
