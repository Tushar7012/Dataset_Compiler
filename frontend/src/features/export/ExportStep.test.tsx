import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { ExportStep } from './ExportStep'

vi.mock('../../api/runs', () => ({
  exportRun: vi.fn(),
  downloadExport: vi.fn(),
}))

import { downloadExport, exportRun } from '../../api/runs'

const mockExportRun = vi.mocked(exportRun)
const mockDownloadExport = vi.mocked(downloadExport)

describe('ExportStep', () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => 'blob:mock-url')
    URL.revokeObjectURL = vi.fn()
  })

  it('renders a Download export button', () => {
    renderWithProviders(<ExportStep runId="run-1" />)

    expect(screen.getByRole('button', { name: /download export/i })).toBeInTheDocument()
  })

  it('has no axe-detectable accessibility violations', async () => {
    const { container } = renderWithProviders(<ExportStep runId="run-1" />)
    await screen.findByRole('button', { name: /download export/i })
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  }, 10_000)

  it('moves focus to the step heading on mount', () => {
    renderWithProviders(<ExportStep runId="run-1" />)
    expect(screen.getByRole('heading', { name: /export dataset/i })).toHaveFocus()
  })

  it('exports then downloads the bundle on click', async () => {
    const user = userEvent.setup()
    mockExportRun.mockResolvedValue({ run_id: 'run-1', export_dir: '/data/x' })
    const blob = new Blob(['zip-bytes'])
    mockDownloadExport.mockResolvedValue(blob)

    renderWithProviders(<ExportStep runId="run-1" />)
    await user.click(screen.getByRole('button', { name: /download export/i }))

    expect(await screen.findByText(/export downloaded/i)).toBeInTheDocument()
    expect(mockExportRun).toHaveBeenCalledWith('run-1')
    expect(mockDownloadExport).toHaveBeenCalledWith('run-1')
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob)
  })

  it('shows an error message if export creation fails', async () => {
    const user = userEvent.setup()
    mockExportRun.mockRejectedValue(new ApiError(409, "run is 'running', not ready to export"))

    renderWithProviders(<ExportStep runId="run-1" />)
    await user.click(screen.getByRole('button', { name: /download export/i }))

    expect(await screen.findByText("run is 'running', not ready to export")).toBeInTheDocument()
  })
})
