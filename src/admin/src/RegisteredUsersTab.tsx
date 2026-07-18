import { useEffect, useMemo, useRef, useState } from 'react'
import {
  getContacts,
  updateGlobalContacts,
  updateFrontendContacts,
  deleteFrontendContacts,
  copyContactsFromFrontend,
  exportContactsURL,
  importContacts,
  listFrontends,
  type Contact,
  type ContactsStore,
  type Frontend,
} from './api'

type Scope = 'global' | `frontend:${string}`
type SortDir = 'asc' | 'desc'

const FIELDS: { key: keyof Contact; label: string }[] = [
  { key: 'email', label: 'Email' },
  { key: 'first_name', label: 'First name' },
  { key: 'last_name', label: 'Last name' },
  { key: 'organization', label: 'Organization' },
  { key: 'country', label: 'Country' },
  { key: 'sector', label: 'Sector' },
  { key: 'registered_by', label: 'Registered by' },
]

const EMPTY_CONTACT: Contact = {
  email: '',
  first_name: '',
  last_name: '',
  organization: '',
  country: '',
  sector: '',
  registered_by: '',
}

function sortKey(scope: Scope): string {
  return `hrdd_admin_users_sort_${scope}`
}

export default function RegisteredUsersTab() {
  const [store, setStore] = useState<ContactsStore | null>(null)
  const [frontends, setFrontends] = useState<Frontend[]>([])
  const [scope, setScope] = useState<Scope>('global')
  const [rows, setRows] = useState<Contact[]>([])
  const [mode, setMode] = useState<'replace' | 'append'>('replace')
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [saving, setSaving] = useState(false)
  const [filter, setFilter] = useState('')
  const [sortCol, setSortCol] = useState<keyof Contact>('email')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [copyFrom, setCopyFrom] = useState<string>('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    reloadAll()
  }, [])

  useEffect(() => {
    const saved = localStorage.getItem(sortKey(scope))
    if (saved) {
      try {
        const { col, dir } = JSON.parse(saved)
        setSortCol(col)
        setSortDir(dir)
      } catch {
        // ignore
      }
    } else {
      setSortCol('email')
      setSortDir('asc')
    }
  }, [scope])

  useEffect(() => {
    if (!store) return
    if (scope === 'global') {
      setRows(store.global.map(c => ({ ...c })))
      setMode('replace')
    } else {
      const fid = scope.slice('frontend:'.length)
      const override = store.per_frontend?.[fid]
      if (override) {
        setRows(override.contacts.map(c => ({ ...c })))
        setMode(override.mode)
      } else {
        setRows([])
        setMode('replace')
      }
    }
    setDirty(false)
  }, [store, scope])

  const reloadAll = async () => {
    try {
      const [s, fs] = await Promise.all([getContacts(), listFrontends()])
      setStore(s)
      setFrontends(fs.frontends || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load contacts')
    }
  }

  const currentFrontendId = scope.startsWith('frontend:') ? scope.slice('frontend:'.length) : ''
  const hasOverride = currentFrontendId ? Boolean(store?.per_frontend?.[currentFrontendId]) : false

  const frontendsWithOverride = useMemo(() => {
    return new Set(Object.keys(store?.per_frontend || {}))
  }, [store])

  const filteredSortedRows = useMemo(() => {
    const f = filter.trim().toLowerCase()
    const filtered = f
      ? rows.filter(r => FIELDS.some(({ key }) => String(r[key] || '').toLowerCase().includes(f)))
      : rows
    const sorted = [...filtered].sort((a, b) => {
      const av = String(a[sortCol] || '').toLowerCase()
      const bv = String(b[sortCol] || '').toLowerCase()
      if (av < bv) return sortDir === 'asc' ? -1 : 1
      if (av > bv) return sortDir === 'asc' ? 1 : -1
      return 0
    })
    return sorted
  }, [rows, filter, sortCol, sortDir])

  const handleSort = (col: keyof Contact) => {
    let nextDir: SortDir = 'asc'
    if (col === sortCol) {
      nextDir = sortDir === 'asc' ? 'desc' : 'asc'
    }
    setSortCol(col)
    setSortDir(nextDir)
    localStorage.setItem(sortKey(scope), JSON.stringify({ col, dir: nextDir }))
  }

  const updateRow = (idx: number, field: keyof Contact, value: string) => {
    // idx references the filtered/sorted list — resolve back to original rows array
    const target = filteredSortedRows[idx]
    setRows(prev => prev.map(r => (r === target ? { ...r, [field]: value } : r)))
    setDirty(true)
  }

  const addRow = () => {
    setRows(prev => [...prev, { ...EMPTY_CONTACT }])
    setDirty(true)
  }

  const deleteRow = (idx: number) => {
    const target = filteredSortedRows[idx]
    setRows(prev => prev.filter(r => r !== target))
    setDirty(true)
  }

  const handleSave = async () => {
    setError('')
    setInfo('')
    setSaving(true)
    try {
      // Strip empty email rows silently (blank rows added but never filled)
      const clean = rows.filter(r => r.email.trim())
      if (scope === 'global') {
        await updateGlobalContacts(clean)
      } else {
        await updateFrontendContacts(currentFrontendId, mode, clean)
      }
      await reloadAll()
      setInfo('Saved.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteOverride = async () => {
    if (!currentFrontendId) return
    if (!confirm(`Remove the custom users list for this frontend? It will fall back to the global list.`)) return
    setError('')
    try {
      await deleteFrontendContacts(currentFrontendId)
      await reloadAll()
      setInfo('Override removed.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  const handleCopyFrom = async () => {
    if (!currentFrontendId || !copyFrom) return
    if (rows.length > 0 && !confirm(`Overwrite the current list with contacts from "${copyFrom}"?`)) return
    setError('')
    try {
      await copyContactsFromFrontend(currentFrontendId, copyFrom, mode)
      await reloadAll()
      setCopyFrom('')
      setInfo('Copied.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Copy failed')
    }
  }

  const handleExport = () => {
    const token = localStorage.getItem('hrdd_admin_token') || ''
    // Use fetch to inject Authorization header, then trigger download
    fetch(exportContactsURL(scope), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(r => {
        if (!r.ok) throw new Error(`Export failed (${r.status})`)
        return r.blob()
      })
      .then(blob => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `authorized_contacts_${scope.replace(':', '_')}.xlsx`
        document.body.appendChild(a)
        a.click()
        a.remove()
        URL.revokeObjectURL(url)
      })
      .catch(err => setError(err instanceof Error ? err.message : 'Export failed'))
  }

  const handleImport = async (file: File) => {
    setError('')
    setInfo('')
    try {
      const res = await importContacts(file, scope)
      await reloadAll()
      setInfo(`Imported: ${res.added} added, ${res.updated} updated, ${res.ignored_malformed} ignored.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed')
    }
  }

  const sortIndicator = (col: keyof Contact) => {
    if (col !== sortCol) return ''
    return sortDir === 'asc' ? ' ▲' : ' ▼'
  }

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <div className="flex items-start justify-between mb-4 gap-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Registered Users</h2>
            <p className="text-sm text-gray-500 mt-1">
              Directory of authorized users. Global list applies everywhere; per-frontend lists can replace or append.
            </p>
          </div>
          <div>
            <label className="text-sm text-gray-700 mr-2">Scope:</label>
            <select
              value={scope}
              onChange={e => setScope(e.target.value as Scope)}
              className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm"
            >
              <option value="global">Global</option>
              {frontends.map(fe => (
                <option key={fe.id} value={`frontend:${fe.id}`}>
                  {fe.name || fe.id}
                  {frontendsWithOverride.has(fe.id) ? '  ◆ custom' : ''}
                </option>
              ))}
            </select>
          </div>
        </div>

        {scope.startsWith('frontend:') && (
          <div className="bg-gray-50 rounded-lg p-4 mb-4 flex flex-wrap items-center gap-4">
            <div>
              <label className="text-sm text-gray-700 mr-2">Mode:</label>
              <select
                value={mode}
                onChange={e => {
                  setMode(e.target.value as 'replace' | 'append')
                  setDirty(true)
                }}
                className="border border-gray-300 rounded-lg px-3 py-1 text-sm"
              >
                <option value="replace">Replace global</option>
                <option value="append">Append to global</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-700">Copy from:</label>
              <select
                value={copyFrom}
                onChange={e => setCopyFrom(e.target.value)}
                className="border border-gray-300 rounded-lg px-3 py-1 text-sm"
              >
                <option value="">— select —</option>
                {frontends
                  .filter(fe => fe.id !== currentFrontendId && frontendsWithOverride.has(fe.id))
                  .map(fe => (
                    <option key={fe.id} value={fe.id}>
                      {fe.name || fe.id}
                    </option>
                  ))}
              </select>
              <button
                onClick={handleCopyFrom}
                disabled={!copyFrom}
                className="bg-uni-blue text-white text-sm px-3 py-1 rounded-lg disabled:opacity-50"
              >
                Copy
              </button>
            </div>
            {hasOverride && (
              <button
                onClick={handleDeleteOverride}
                className="ml-auto text-sm bg-uni-red text-white px-3 py-1 rounded-lg"
              >
                Remove override
              </button>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3 mb-3">
          <input
            type="text"
            placeholder="Filter…"
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[200px]"
          />
          <button onClick={addRow} className="text-sm bg-uni-blue text-white px-3 py-1.5 rounded-lg">
            Add row
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !dirty}
            className="text-sm bg-uni-blue text-white px-3 py-1.5 rounded-lg disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button onClick={handleExport} className="text-sm border border-gray-300 px-3 py-1.5 rounded-lg">
            Export .xlsx
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            className="text-sm border border-gray-300 px-3 py-1.5 rounded-lg"
          >
            Import .xlsx / .csv
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.csv"
            hidden
            onChange={e => {
              const f = e.target.files?.[0]
              if (f) handleImport(f)
              e.target.value = ''
            }}
          />
        </div>

        {error && <div className="bg-red-50 border border-red-200 text-uni-red text-sm rounded-lg p-2 mb-3">{error}</div>}
        {info && <div className="bg-green-50 border border-green-200 text-green-700 text-sm rounded-lg p-2 mb-3">{info}</div>}

        <div className="overflow-x-auto border border-gray-200 rounded-lg">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {FIELDS.map(({ key, label }) => (
                  <th
                    key={key}
                    onClick={() => handleSort(key)}
                    className="px-3 py-2 text-left font-medium text-gray-700 cursor-pointer hover:bg-gray-100 select-none"
                  >
                    {label}
                    {sortIndicator(key)}
                  </th>
                ))}
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {filteredSortedRows.length === 0 && (
                <tr>
                  <td colSpan={FIELDS.length + 1} className="px-3 py-4 text-center text-gray-500">
                    No users. Add one or import from Excel/CSV.
                  </td>
                </tr>
              )}
              {filteredSortedRows.map((row, idx) => (
                <tr key={idx} className="border-b border-gray-100 last:border-0">
                  {FIELDS.map(({ key }) => (
                    <td key={key} className="px-2 py-1">
                      <input
                        type="text"
                        value={row[key] || ''}
                        onChange={e => updateRow(idx, key, e.target.value)}
                        className="w-full border border-transparent focus:border-gray-300 rounded px-2 py-1 text-sm"
                      />
                    </td>
                  ))}
                  <td className="px-2 py-1 text-right">
                    <button
                      onClick={() => deleteRow(idx)}
                      className="text-uni-red text-sm hover:underline"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="text-xs text-gray-500 mt-3">
          Import is additive: existing emails are updated, new emails are added, and emails not in the file are preserved.
        </p>
      </div>
    </div>
  )
}
