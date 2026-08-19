import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'
import { renderWithProviders } from './test-utils'
import App from './App'

vi.mock('./api/projects', () => ({
  createProject: vi.fn().mockResolvedValue({ id: 'proj-1', name: 'Project x', created_at: '2026-08-15T00:00:00Z' }),
  uploadSource: vi.fn(),
}))

describe('App', () => {
  it('renders the Dataset Compiler heading and the first wizard step', async () => {
    renderWithProviders(<App />)
    expect(screen.getByRole('heading', { name: 'Dataset Compiler' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: /upload sources/i })).toBeInTheDocument()
  })

  it('has no axe-detectable accessibility violations', async () => {
    const { container } = renderWithProviders(<App />)
    await screen.findByRole('heading', { name: /upload sources/i })
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  }, 10_000)
})
