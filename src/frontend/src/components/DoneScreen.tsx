import { useState } from 'react'
import { downloadJob } from '../api'
import { useT } from '../i18n'
import { Button, Card } from './ui'
import { Banner } from './Banner'

export function DoneScreen({
  token, jobRef, onRestart, name,
}: {
  token: string
  jobRef: string
  onRestart?: () => void
  name?: string
}) {
  const t = useT()
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
      setError(t('done.errExpired'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      {name && <p className="mb-1 text-[0.8125rem] font-medium text-text-secondary">{name}</p>}
      <h1 className="mb-1 text-[1.5rem] font-semibold text-secondary">{t('done.title')}</h1>
      <p className="mb-5 text-sm text-text-secondary">{t('done.intro')}</p>
      <div className="space-y-3">
        <Button variant="accent" onClick={download} disabled={busy}>
          {busy ? t('done.preparing') : t('done.download')}
        </Button>
        {onRestart && <Button variant="ghost" onClick={onRestart}>{t('done.another')}</Button>}
        {error && <Banner kind="danger">{error}</Banner>}
      </div>
    </Card>
  )
}
