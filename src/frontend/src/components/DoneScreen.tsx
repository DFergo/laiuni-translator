import { useState } from 'react'
import { downloadJob } from '../api'
import { Button, Card } from './ui'
import { Banner } from './Banner'

export function DoneScreen({
  token, jobRef, onRestart,
}: {
  token: string
  jobRef: string
  onRestart: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function download() {
    setBusy(true); setError('')
    try {
      const blob = await downloadJob(token, jobRef)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `translations-${jobRef}.zip`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch {
      setError('This download is no longer available (it may have expired).')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <h1 className="mb-1 text-[1.5rem] font-semibold text-secondary">Translation ready</h1>
      <p className="mb-5 text-sm text-text-secondary">
        We’ve emailed you the original and all translations. You can also download them here while they’re available (48 hours).
      </p>
      <div className="space-y-3">
        <Button variant="accent" onClick={download} disabled={busy}>
          {busy ? 'Preparing…' : 'Download all (.zip)'}
        </Button>
        <Button variant="ghost" onClick={onRestart}>Translate another document</Button>
        {error && <Banner kind="danger">{error}</Banner>}
      </div>
    </Card>
  )
}
