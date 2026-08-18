import { test, expect } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import fs from 'node:fs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const fixtureDir = path.join(__dirname, 'fixtures')

test.describe('CPT website flow', () => {
  test('create project, analyze model, CPT plan, preview, export', async ({ page }) => {
    fs.mkdirSync(fixtureDir, { recursive: true })
    const docPath = path.join(fixtureDir, 'policy.md')
    fs.writeFileSync(
      docPath,
      '# Policy\n\nRemote work requires VPN. Employees complete annual security training.\n',
    )

    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Project setup' })).toBeVisible()

    await page.getByLabel(/project name/i).fill('E2E CPT')
    await page.getByRole('button', { name: /create project/i }).click()
    await expect(page.getByRole('heading', { name: /upload sources/i })).toBeVisible()

    await page.getByLabel(/upload/i).setInputFiles(docPath)
    await expect(page.getByText('policy.md')).toBeVisible({ timeout: 60_000 })
    await page.getByRole('button', { name: /continue/i }).click()

    await expect(page.getByRole('heading', { name: /model selection/i })).toBeVisible()
    await page.getByLabel(/^model$/i).fill('gpt2')
    await page.getByRole('button', { name: /analyze/i }).click()
    await expect(page.getByRole('button', { name: /continue/i })).toBeEnabled({ timeout: 180_000 })
    await page.getByRole('button', { name: /continue/i }).click()

    await expect(page.getByRole('heading', { name: /suggested training goal/i })).toBeVisible()
    await page.getByRole('button', { name: /skip/i }).click()

    // Provider configuration precedes goal selection in the wizard (the
    // training goal isn't known yet at this point — see ProviderConfigStep).
    await expect(page.getByRole('heading', { name: /provider configuration/i })).toBeVisible()
    await page.getByLabel(/provider name/i).fill('local-stub')
    await page.getByLabel(/base url/i).fill('http://127.0.0.1:8765/v1')
    await page.getByLabel(/^model$/i).fill('stub-model')
    await page.getByRole('button', { name: /create provider/i }).click()

    await expect(page.getByRole('heading', { name: /judge model/i })).toBeVisible()
    await page.getByRole('button', { name: /skip.*no judge model/i }).click()

    await expect(page.getByRole('heading', { name: /provider ready/i })).toBeVisible()
    // Consent is only required if this server has a remote provider or remote
    // document parsing configured — both local here, but stay robust to a
    // dev environment where TUNEFORGE_DOCLING_REMOTE_URL is set. Whether the
    // checkbox is needed is only known once ProviderConfigStep's own
    // remote-parsing-enabled query resolves, so wait for it rather than a
    // one-shot count() that can read 0 in the split second before it mounts.
    const consentCheckbox = page.getByRole('checkbox')
    const consentAppeared = await consentCheckbox
      .waitFor({ state: 'visible', timeout: 5_000 })
      .then(() => true)
      .catch(() => false)
    if (consentAppeared) {
      await consentCheckbox.check()
    }
    await page.getByRole('button', { name: /continue/i }).click()

    await expect(page.getByRole('heading', { name: /^training goal$/i })).toBeVisible()
    await page.getByLabel(/training goal/i).selectOption('domain_adaptation')
    await page.getByLabel(/desired behavior/i).fill('Adapt to company policy language.')
    await expect(page.getByRole('button', { name: /get recommendation/i })).toBeEnabled({
      timeout: 120_000,
    })
    await page.getByRole('button', { name: /get recommendation/i }).click()

    await expect(page.getByRole('heading', { name: /confirm training plan/i })).toBeVisible({
      timeout: 60_000,
    })
    await page.getByRole('button', { name: /approve/i }).click()

    await expect(page.getByRole('heading', { name: /^preview$/i })).toBeVisible()
    await page.getByRole('button', { name: /generate preview/i }).click()
    await expect(page.getByRole('button', { name: /approve full run/i })).toBeVisible({
      timeout: 180_000,
    })
    await page.getByRole('button', { name: /approve full run/i }).click()

    await expect(page.getByRole('heading', { name: /run progress/i })).toBeVisible()
    await expect(page.getByRole('heading', { name: /export dataset/i })).toBeVisible({
      timeout: 300_000,
    })

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: /download export/i }).click(),
    ])
    const out = path.join(fixtureDir, await download.suggestedFilename())
    await download.saveAs(out)
    expect(fs.statSync(out).size).toBeGreaterThan(100)
  })
})
