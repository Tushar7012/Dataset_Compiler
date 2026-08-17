import 'vitest'
import type { AxeResults } from 'axe-core'

declare module 'vitest' {
  interface Assertion<T = unknown> {
    toHaveNoViolations(): T extends AxeResults ? void : never
  }
  interface AsymmetricMatchersContaining {
    toHaveNoViolations(): void
  }
}

export {}
