import { defineConfig, devices } from '@playwright/test'

const BACKEND = 'http://127.0.0.1:8420'

export default defineConfig({
  testDir: './e2e',
  timeout: 180_000,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: BACKEND,
    trace: 'on-first-retry',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: 'uv run python -m tuneforge.main',
    cwd: '../backend',
    url: `${BACKEND}/api/health`,
    reuseExistingServer: true,
    timeout: 120_000,
  },
})
