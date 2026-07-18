import { useState, useEffect } from 'react'
import {
  listPrompts, readPrompt, savePrompt,
  getPromptMode, setPromptMode,
  copyPromptsToFrontend, deleteFrontendPrompts, listCustomPromptFrontends,
  resetPrompt, resetGlobalPrompts,
  listFrontends, getFrontendConfig,
  type PromptFile, type Frontend, type FrontendConfig
} from './api'

// Sprint 23 scoping: map a prompt filename to the profile/mode it belongs to.
// Role/mode-specific prompts are shown only when active on the frontend; all
// other (shared) prompts are always shown.
const MODE_TO_SUFFIX: Record<string, string> = {
  documentation: 'document', interview: 'interview', advisory: 'advisory', submit: 'submit', training: 'training',
}
const WIRED_MODES: Record<string, string[]> = {
  organizer: ['documentation', 'interview', 'advisory', 'submit'],
  officer: ['documentation', 'interview', 'advisory', 'submit', 'training'],
}

function promptVisible(name: string, cfg: FrontendConfig | null): boolean {
  if (!cfg) return true
  const profiles = cfg.profiles || []
  const activeSuffixes = (role: string): string[] => {
    const m = (cfg.modes?.[role] && cfg.modes[role].length > 0) ? cfg.modes[role] : (WIRED_MODES[role] || [])
    return m.map(mode => MODE_TO_SUFFIX[mode]).filter(Boolean)
  }
  const base = name.replace(/\.md$/, '')

  if (base === 'worker') return profiles.includes('worker')
  if (base === 'worker_representative') return profiles.includes('representative')
  for (const role of ['organizer', 'officer']) {
    if (base.startsWith(role + '_')) {
      if (!profiles.includes(role)) return false
      return activeSuffixes(role).includes(base.slice(role.length + 1))
    }
  }
  const ss = base.match(/^session_summary_(worker|representative|organizer|officer)$/)
  if (ss) return profiles.includes(ss[1])

  return true  // shared prompts (core, context_template, evidence_summary, …)
}

export default function PromptsTab() {
  const [categories, setCategories] = useState<Record<string, PromptFile[]>>({})
  const [selected, setSelected] = useState<string | null>(null)
  const [content, setContent] = useState('')
  const [originalContent, setOriginalContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(true)

  // Sprint 8h: prompt mode + frontend selector
  const [mode, setMode] = useState<'global' | 'per_frontend'>('global')
  const [frontends, setFrontends] = useState<Frontend[]>([])
  const [selectedFrontend, setSelectedFrontend] = useState<string>('')
  const [feConfig, setFeConfig] = useState<FrontendConfig | null>(null)  // Sprint 23 scoping

  const loadFeConfig = async (fid: string) => {
    try { const { config } = await getFrontendConfig(fid); setFeConfig(config) } catch { setFeConfig(null) }
  }

  useEffect(() => {
    loadInitial()
  }, [])

  const loadInitial = async () => {
    try {
      const [modeData, feData] = await Promise.all([
        getPromptMode(),
        listFrontends(),
      ])
      setMode(modeData.mode as 'global' | 'per_frontend')
      setFrontends(feData.frontends)
      if (modeData.mode === 'per_frontend' && feData.frontends.length > 0) {
        setSelectedFrontend(feData.frontends[0].id)
        await loadFeConfig(feData.frontends[0].id)
        await loadPrompts(feData.frontends[0].id)
      } else {
        await loadPrompts()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }

  const loadPrompts = async (frontendId?: string) => {
    try {
      const fid = mode === 'per_frontend' ? (frontendId || selectedFrontend) : undefined
      const data = await listPrompts(fid)
      setCategories(data.categories)
      setSelected(null)
      setContent('')
      setOriginalContent('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load prompts')
    }
  }

  const selectPrompt = async (name: string) => {
    setError('')
    setSuccess('')
    try {
      const fid = mode === 'per_frontend' ? selectedFrontend : undefined
      const data = await readPrompt(name, fid)
      setSelected(name)
      setContent(data.content)
      setOriginalContent(data.content)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load prompt')
    }
  }

  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const fid = mode === 'per_frontend' ? selectedFrontend : undefined
      await savePrompt(selected, content, fid)
      setOriginalContent(content)
      setSuccess('Saved')
      setTimeout(() => setSuccess(''), 3000)
      loadPrompts(fid)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const handleModeToggle = async () => {
    const newMode = mode === 'global' ? 'per_frontend' : 'global'
    setError('')
    setSuccess('')

    // Sprint 23 guard: switching per_frontend → global stops every frontend
    // with a custom set from using it. Confirm, naming the affected frontends.
    if (newMode === 'global') {
      try {
        const { frontends: custom } = await listCustomPromptFrontends()
        if (custom.length > 0) {
          const names = custom.map(f => f.name).join(', ')
          if (!confirm(
            `Switching to Global will make these frontends STOP using their custom prompts and use the shared global set instead: ${names}.\n\n` +
            `Their custom prompt files are kept on disk but ignored. Continue?`
          )) return
        }
      } catch { /* if the check fails, fall through — the switch itself is non-destructive on disk */ }
    }

    try {
      await setPromptMode(newMode)
      setMode(newMode)
      if (newMode === 'per_frontend' && frontends.length > 0) {
        setSelectedFrontend(frontends[0].id)
        await loadFeConfig(frontends[0].id)
        await loadPrompts(frontends[0].id)
        setSuccess('Switched to Per Frontend. Global prompts copied to frontends without custom sets.')
      } else {
        setSelectedFrontend('')
        setFeConfig(null)
        await loadPrompts()
        setSuccess('Switched to Global. All frontends now use the same prompts.')
      }
      setTimeout(() => setSuccess(''), 5000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to change mode')
    }
  }

  const handleResetPrompt = async () => {
    if (!selected) return
    const fid = mode === 'per_frontend' ? selectedFrontend : undefined
    const target = fid ? 'the current global version' : 'the factory default'
    if (!confirm(`Reset "${selected}" to ${target}?\n\nYour current changes to this prompt will be lost. This cannot be undone.`)) return
    setError('')
    try {
      const { content: c } = await resetPrompt(selected, fid)
      setContent(c)
      setOriginalContent(c)
      setSuccess('Reset to default')
      setTimeout(() => setSuccess(''), 3000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset failed')
    }
  }

  const handleResetGlobal = async () => {
    if (!confirm('Reset ALL global prompts to the factory defaults?\n\nPer-frontend custom sets are NOT affected. This cannot be undone.')) return
    setError('')
    try {
      const { reset } = await resetGlobalPrompts()
      setSuccess(`Reset ${reset} global prompts to factory defaults`)
      setTimeout(() => setSuccess(''), 3000)
      await loadPrompts()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset failed')
    }
  }

  const handleFrontendChange = async (fid: string) => {
    setSelectedFrontend(fid)
    setError('')
    setSuccess('')
    await loadFeConfig(fid)
    await loadPrompts(fid)
  }

  const handleCopyFromGlobal = async () => {
    if (!selectedFrontend) return
    setError('')
    try {
      const result = await copyPromptsToFrontend(selectedFrontend)
      setSuccess(`Copied ${result.copied} prompts from global`)
      setTimeout(() => setSuccess(''), 3000)
      await loadPrompts(selectedFrontend)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Copy failed')
    }
  }

  const handleDeleteCustom = async () => {
    if (!selectedFrontend) return
    const feName = frontends.find(f => f.id === selectedFrontend)?.name || selectedFrontend
    const count = Object.values(categories).reduce((n, files) => n + files.length, 0)
    if (!confirm(
      `Delete all ${count} custom prompt(s) for frontend "${feName}"?\n\n` +
      `This permanently removes its custom set; the frontend reverts to the global prompts. This cannot be undone.`
    )) return
    setError('')
    try {
      const result = await deleteFrontendPrompts(selectedFrontend)
      setSuccess(`Deleted ${result.deleted} custom prompts`)
      setTimeout(() => setSuccess(''), 3000)
      await loadPrompts(selectedFrontend)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  const formatDate = (ts: number | null) => {
    if (!ts) return '—'
    return new Date(ts * 1000).toLocaleString()
  }

  const dirty = content !== originalContent

  // Sprint 23: scope the list to the frontend's active profiles/modes (per_frontend
  // mode with a loaded config); global mode (feConfig null) shows everything.
  const visibleCategories = Object.entries(categories)
    .map(([cat, files]) => [cat, files.filter(f => promptVisible(f.name, feConfig))] as [string, PromptFile[]])
    .filter(([, files]) => files.length > 0)

  if (loading) return <p className="text-gray-400 text-sm">Loading...</p>

  return (
    <div className="space-y-4">
      {/* Mode toggle + frontend selector */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium text-gray-700">Prompt Mode:</span>
            <div className="flex items-center gap-2">
              <span className={`text-sm ${mode === 'global' ? 'font-semibold text-uni-blue' : 'text-gray-400'}`}>Global</span>
              <div
                className={`relative w-10 h-5 rounded-full transition-colors cursor-pointer ${mode === 'per_frontend' ? 'bg-uni-blue' : 'bg-gray-300'}`}
                onClick={handleModeToggle}
              >
                <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${mode === 'per_frontend' ? 'translate-x-5' : 'translate-x-0.5'}`} />
              </div>
              <span className={`text-sm ${mode === 'per_frontend' ? 'font-semibold text-uni-blue' : 'text-gray-400'}`}>Per Frontend</span>
            </div>
          </div>

          {mode === 'per_frontend' && frontends.length > 0 && (
            <div className="flex items-center gap-2">
              <select
                value={selectedFrontend}
                onChange={e => handleFrontendChange(e.target.value)}
                className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
              >
                {frontends.map(fe => (
                  <option key={fe.id} value={fe.id}>{fe.name || fe.id}</option>
                ))}
              </select>
              <button
                onClick={handleCopyFromGlobal}
                className="border border-gray-300 text-gray-600 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors hover:bg-gray-50"
              >
                Copy from Global
              </button>
              <button
                onClick={handleDeleteCustom}
                className="text-xs text-uni-red hover:underline px-2 py-1.5"
              >
                Delete Custom Set
              </button>
            </div>
          )}
          {mode === 'global' && (
            <button
              onClick={handleResetGlobal}
              className="border border-gray-300 text-gray-600 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors hover:bg-gray-50"
            >
              Reset all to factory
            </button>
          )}
        </div>
        <p className="text-xs text-gray-400 mt-2">
          {mode === 'global'
            ? 'All frontends use the same set of prompts.'
            : 'Each frontend has its own set of prompts. Select a frontend to edit its prompts.'}
        </p>
      </div>

      {error && <p className="text-sm text-uni-red">{error}</p>}
      {success && <p className="text-sm text-green-600">{success}</p>}

      {/* Prompt editor */}
      <div className="flex gap-6 h-[calc(100vh-280px)]">
        {/* Left: file list */}
        <div className="w-72 flex-shrink-0 overflow-y-auto">
          {visibleCategories.map(([category, files]) => (
            <div key={category} className="mb-4">
              <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-2">
                {category}
              </h4>
              {files.map(file => (
                <button
                  key={file.name}
                  onClick={() => selectPrompt(file.name)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                    selected === file.name
                      ? 'bg-uni-blue text-white'
                      : 'text-gray-700 hover:bg-gray-100'
                  }`}
                >
                  <div className="font-medium">{file.name}</div>
                  <div className={`text-xs ${selected === file.name ? 'text-white/70' : 'text-gray-400'}`}>
                    {formatDate(file.modified)}
                  </div>
                </button>
              ))}
            </div>
          ))}
        </div>

        {/* Right: editor */}
        <div className="flex-1 flex flex-col">
          {selected ? (
            <>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-lg font-semibold text-gray-800">{selected}</h3>
                <div className="flex items-center gap-3">
                  {dirty && <span className="text-xs text-gray-400">Unsaved changes</span>}
                  <button
                    onClick={() => selected && (!dirty || confirm('Reload from disk and discard unsaved changes?')) && selectPrompt(selected)}
                    className="border border-gray-300 text-gray-600 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors hover:bg-gray-50"
                    title="Re-read this prompt from disk (picks up edits made directly on the server)"
                  >
                    Reload from disk
                  </button>
                  <button
                    onClick={handleResetPrompt}
                    className="border border-gray-300 text-gray-600 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors hover:bg-gray-50"
                    title={mode === 'per_frontend' ? 'Reset this prompt to the global version' : 'Reset this prompt to the factory default'}
                  >
                    Reset to default
                  </button>
                  <button
                    onClick={handleSave}
                    disabled={saving || !dirty}
                    className="bg-uni-blue text-white rounded-lg px-4 py-1.5 text-sm font-medium transition-colors hover:opacity-90 disabled:opacity-50"
                  >
                    {saving ? 'Saving...' : 'Save'}
                  </button>
                </div>
              </div>
              <textarea
                value={content}
                onChange={e => setContent(e.target.value)}
                className="flex-1 border border-gray-300 rounded-lg p-4 font-mono text-sm resize-none focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
                spellCheck={false}
              />
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <p className="text-gray-400 text-sm">Select a prompt file to edit</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
