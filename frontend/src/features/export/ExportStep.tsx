import { useState } from 'react'
import { downloadExport, exportRun } from '../../api/runs'
import { ApiError } from '../../api/client'

interface ExportStepProps {
  runId: string
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function ExportStep({ runId }: ExportStepProps) {
  const [isExporting, setIsExporting] = useState(false)
  const [downloaded, setDownloaded] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleExport = async () => {
    setError(null)
    setIsExporting(true)
    try {
      await exportRun(runId)
      const blob = await downloadExport(runId)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `tuneforge-export-${runId}.zip`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setDownloaded(true)
    } catch (caught: unknown) {
      setError(errorMessage(caught))
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <section>
      <h2>Export dataset</h2>
      <button type="button" disabled={isExporting} onClick={() => void handleExport()}>
        Download export
      </button>
      {downloaded && <p>Export downloaded.</p>}
      {error && <p role="alert">{error}</p>}

      <div>
        <h3>Using this in Unsloth</h3>
        <p>
          Load the exported Parquet/JSONL files with Hugging Face <code>datasets</code> (
          <code>load_dataset(&quot;parquet&quot;, data_files=...)</code> or{' '}
          <code>load_dataset(&quot;json&quot;, data_files=...)</code>) and pass the result straight into Unsloth's
          trainer for this plan's objective (<code>SFTTrainer</code> for prompt-completion/conversation,{' '}
          <code>DPOTrainer</code> for preference pairs) — the exported schema already matches what each expects.
        </p>
      </div>
    </section>
  )
}
