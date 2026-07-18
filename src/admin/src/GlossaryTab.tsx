import { useState, useEffect, useRef } from 'react'
import {
  getGlossaryCoverage, uploadGlossary, setFrontendGlossaryMode, deleteFrontendGlossary,
  listFrontends, getLLMSettings, updateLLMSettings, type GlossaryCoverage, type Frontend,
} from './api'

const toggle = (on: boolean, onClick: () => void) => (
  <div className={`relative w-10 h-5 rounded-full transition-colors flex-shrink-0 ${on ? 'bg-uni-blue' : 'bg-gray-300'}`} onClick={onClick}>
    <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${on ? 'translate-x-5' : 'translate-x-0.5'}`} />
  </div>
)

function CoverageLine({ label, c }: { label: string; c?: { term_count: number; languages: string[] } | null }) {
  if (!c) return <p className="text-xs text-gray-400">{label}: —</p>
  return (
    <p className="text-sm text-gray-700">
      <span className="font-medium">{label}:</span> {c.term_count} terms · {c.languages.length} languages
      {c.languages.length > 0 && <span className="text-xs text-gray-400 ml-2">({c.languages.join(', ')})</span>}
    </p>
  )
}

export default function GlossaryTab() {
  const [cov, setCov] = useState<GlossaryCoverage | null>(null)
  const [frontends, setFrontends] = useState<Frontend[]>([])
  const [fid, setFid] = useState<string>('')
  const [feCov, setFeCov] = useState<GlossaryCoverage | null>(null)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [glossaryEnabled, setGlossaryEnabled] = useState<boolean | null>(null)
  const baseInput = useRef<HTMLInputElement>(null)
  const feInput = useRef<HTMLInputElement>(null)

  const flash = (m: string) => { setMsg(m); setTimeout(() => setMsg(''), 3000) }

  const loadBase = async () => {
    try { setCov(await getGlossaryCoverage()) } catch (e) { setErr(e instanceof Error ? e.message : 'Load failed') }
  }
  const loadFe = async (id: string) => {
    if (!id) { setFeCov(null); return }
    try { setFeCov(await getGlossaryCoverage(id)) } catch { setFeCov(null) }
  }

  useEffect(() => {
    loadBase()
    listFrontends().then(({ frontends: f }) => setFrontends(f)).catch(() => {})
    getLLMSettings().then(s => setGlossaryEnabled(s.translation_glossary_enabled)).catch(() => {})
  }, [])

  const toggleIgnore = async () => {
    if (glossaryEnabled === null) return
    const next = !glossaryEnabled
    setGlossaryEnabled(next)
    try { await updateLLMSettings({ translation_glossary_enabled: next }) }
    catch (e) { setGlossaryEnabled(!next); setErr(e instanceof Error ? e.message : 'Failed') }
  }

  const onBaseFile = async (f: File | null) => {
    if (!f) return
    setErr('')
    try { const r = await uploadGlossary(f); flash(`Base glossary replaced (${r.terms} terms)`); await loadBase() }
    catch (e) { setErr(e instanceof Error ? e.message : 'Upload failed') }
    if (baseInput.current) baseInput.current.value = ''
  }

  const onFeFile = async (f: File | null) => {
    if (!f || !fid) return
    setErr('')
    try { const r = await uploadGlossary(f, fid); flash(`Per-server glossary set (${r.terms} terms)`); await loadFe(fid) }
    catch (e) { setErr(e instanceof Error ? e.message : 'Upload failed') }
    if (feInput.current) feInput.current.value = ''
  }

  const setMode = async (mode: 'append' | 'replace') => {
    if (!fid) return
    try { await setFrontendGlossaryMode(fid, mode); await loadFe(fid) }
    catch (e) { setErr(e instanceof Error ? e.message : 'Failed') }
  }

  const removeFe = async () => {
    if (!fid || !confirm('Remove this frontend’s glossary and revert to the base?')) return
    try { await deleteFrontendGlossary(fid); flash('Per-server glossary removed'); await loadFe(fid) }
    catch (e) { setErr(e instanceof Error ? e.message : 'Failed') }
  }

  const mode = feCov?.config?.mode ?? 'append'
  const hasServer = !!feCov?.server

  return (
    <div className="space-y-6">
      {/* Glossary usage */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <label className="flex items-start gap-3 cursor-pointer">
          {toggle(glossaryEnabled === false, toggleIgnore)}
          <div>
            <span className="text-sm font-medium text-gray-700">Ignore glossary <span className="font-normal text-gray-400">(Off is recommended)</span></span>
            <p className="text-xs text-gray-400">
              When on, translations run without any glossary — base, per-server, and per-job user terms are all skipped.
            </p>
          </div>
        </label>
      </div>

      {/* Base glossary */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-1">Base glossary</h3>
        <p className="text-xs text-gray-400 mb-4">
          The union's shared terminology, applied to every translation. Replace it by uploading a whole JSON file
          (<code>{`{"terms":[{"term","translations":{lang:str},"note"?}]}`}</code>). No per-term editor.
        </p>
        <CoverageLine label="Loaded" c={cov?.base} />
        <div className="mt-4 flex items-center gap-3">
          <button onClick={() => baseInput.current?.click()} className="text-xs px-3 py-1.5 rounded-lg bg-uni-blue text-white font-medium hover:opacity-90">
            Upload / replace base (JSON)
          </button>
          <input ref={baseInput} type="file" accept=".json,application/json" className="hidden" onChange={e => onBaseFile(e.target.files?.[0] ?? null)} />
          {msg && <span className="text-xs text-green-600">{msg}</span>}
        </div>
      </div>

      {/* Per-server glossary */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-1">Per-server glossary</h3>
        <p className="text-xs text-gray-400 mb-4">
          Give a specific frontend its own terminology. <span className="font-medium">Append</span> reinforces the base
          (server wins on conflicts); <span className="font-medium">Replace</span> uses only the server list. The per-job
          user glossary always wins. Precedence: user &gt; server &gt; base.
        </p>

        <select value={fid} onChange={e => { setFid(e.target.value); loadFe(e.target.value) }}
          className="w-full max-w-sm border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-uni-blue">
          <option value="">— select a frontend —</option>
          {frontends.map(f => <option key={f.id} value={f.id}>{f.name} ({f.id})</option>)}
        </select>

        {fid && feCov && (
          <div className="mt-4 border-t border-gray-200 pt-4 space-y-4">
            <div className="space-y-1">
              <CoverageLine label="Base" c={feCov.base} />
              <CoverageLine label="This server" c={feCov.server} />
              <CoverageLine label="Effective (used for jobs)" c={feCov.effective} />
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-gray-600">Mode:</span>
              {(['append', 'replace'] as const).map(m => (
                <button key={m} onClick={() => setMode(m)}
                  className={`text-xs px-3 py-1 rounded-lg border ${mode === m ? 'bg-uni-blue text-white border-uni-blue' : 'border-gray-300 text-gray-600 hover:bg-gray-50'}`}>
                  {m === 'append' ? 'Append (base + server)' : 'Replace (server only)'}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-3">
              <button onClick={() => feInput.current?.click()} className="text-xs px-3 py-1.5 rounded-lg bg-uni-blue text-white font-medium hover:opacity-90">
                Upload server glossary (JSON)
              </button>
              <input ref={feInput} type="file" accept=".json,application/json" className="hidden" onChange={e => onFeFile(e.target.files?.[0] ?? null)} />
              {hasServer && (
                <button onClick={removeFe} className="text-xs text-gray-400 hover:text-uni-red">Remove server glossary</button>
              )}
            </div>
          </div>
        )}
      </div>

      {err && <p className="text-sm text-uni-red">{err}</p>}
    </div>
  )
}
