import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { useFocusOnMount } from './useFocusOnMount'

function Probe() {
  const ref = useFocusOnMount<HTMLHeadingElement>()
  return (
    <h2 ref={ref} tabIndex={-1}>
      Step heading
    </h2>
  )
}

describe('useFocusOnMount', () => {
  it('moves focus to the ref target on mount', () => {
    const { getByText } = render(<Probe />)
    expect(getByText('Step heading')).toHaveFocus()
  })
})
