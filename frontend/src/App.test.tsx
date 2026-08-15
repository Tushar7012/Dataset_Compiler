import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from './test-utils'
import App from './App'

describe('App', () => {
  it('renders the TuneForge heading and the first wizard step', () => {
    renderWithProviders(<App />)
    expect(screen.getByRole('heading', { name: 'TuneForge' })).toBeInTheDocument()
    expect(screen.getByLabelText(/project name/i)).toBeInTheDocument()
  })
})
