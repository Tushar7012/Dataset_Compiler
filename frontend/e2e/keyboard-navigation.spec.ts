import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import fs from 'node:fs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const fixtureDir = path.join(__dirname, 'fixtures')

async function focusedElement(page: Page) {
  return page.evaluate(() => {
    const el = document.activeElement
    return el ? { tag: el.tagName, text: el.textContent?.trim(), type: (el as HTMLInputElement).type } : null
  })
}

async function expectFocusedHeading(page: Page, text: string | RegExp) {
  await expect(page.locator(':focus')).toHaveText(text)
  const focused = await focusedElement(page)
  expect(focused?.tag).toBe('H2')
}

test.describe('Keyboard-only wizard navigation', () => {
  test('drive all 10 steps using only Tab/Enter/Space, no mouse', async ({ page }) => {
    fs.mkdirSync(fixtureDir, { recursive: true })
    const docPath = path.join(fixtureDir, 'kb-policy.md')
    fs.writeFileSync(docPath, '# Policy\n\nRemote work requires VPN.\n')

    // Step 1: Project setup
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Project setup' })).toBeVisible()

    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'INPUT' })
    await page.keyboard.type('Keyboard-only Project')

    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: 'Create project' })
    await page.keyboard.press('Enter')

    // Step 1b: Upload sources (same step component, second screen)
    await expect(page.getByRole('heading', { name: /upload sources/i })).toBeVisible()
    await expectFocusedHeading(page, /upload sources/i)

    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'INPUT', type: 'file' })

    // Native file inputs cannot be driven by simulated keystrokes (the OS
    // picker they open on Enter/Space is outside the DOM) — this is the one
    // control Playwright's own keyboard API can't reach, same limitation any
    // browser automation has. setInputFiles is the standard stand-in; a real
    // keyboard user still just presses Enter on this same focused control.
    await page.getByLabel(/upload/i).setInputFiles(docPath)
    await expect(page.getByRole('button', { name: /continue/i })).toBeEnabled({ timeout: 60_000 })

    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: /continue/i })
    await page.keyboard.press('Enter')

    // Step 2: Model selection
    await expectFocusedHeading(page, /model selection/i)
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'SELECT' })
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'INPUT' })
    await page.keyboard.type('gpt2')
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: /analyze/i })
    await page.keyboard.press('Enter')

    await expect(page.getByRole('button', { name: /continue/i })).toBeEnabled({ timeout: 180_000 })
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: /continue/i })
    await page.keyboard.press('Enter')

    // Step 3: Suggested training goal — verify the consent checkbox itself is
    // keyboard-operable (Space toggles it), then skip via keyboard.
    await expectFocusedHeading(page, /suggested training goal/i)
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'INPUT', type: 'checkbox' })
    const geminiCheckbox = page.getByRole('checkbox')
    await expect(geminiCheckbox).not.toBeChecked()
    await page.keyboard.press('Space')
    await expect(geminiCheckbox).toBeChecked()
    await page.keyboard.press('Space')
    await expect(geminiCheckbox).not.toBeChecked()

    // "Get AI suggestion" is disabled without consent, so it is skipped in
    // the tab order — the next stop must be "Skip".
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: /skip/i })
    await page.keyboard.press('Enter')

    // Step 4: Provider configuration — precedes goal selection in the wizard
    // (the training goal isn't known yet here, see ProviderConfigStep).
    await expectFocusedHeading(page, /provider configuration/i)
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: /use hugging face router/i })
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'INPUT' })
    await page.keyboard.type('local-stub')
    await page.keyboard.press('Tab')
    await page.keyboard.type('http://127.0.0.1:8765/v1')
    await page.keyboard.press('Tab')
    await page.keyboard.type('stub-model')
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'SELECT' })
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'INPUT', type: 'password' })
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: /create provider/i })
    await page.keyboard.press('Enter')

    // Step 5: Judge model choice — always shown after the generator is
    // created, regardless of which training goal is picked later.
    await expectFocusedHeading(page, /judge model/i)
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: /add judge provider/i })
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: /skip.*no judge model/i })
    await page.keyboard.press('Enter')

    // Step 6: Provider ready. Consent is only shown if this server has a
    // remote provider or remote document parsing configured — both local
    // here, but stay robust to a dev environment where
    // TUNEFORGE_DOCLING_REMOTE_URL is set (async, may not have resolved
    // the instant the heading appears).
    await expectFocusedHeading(page, /provider ready/i)
    const readyCheckbox = page.getByRole('checkbox')
    const consentAppeared = await readyCheckbox
      .waitFor({ state: 'visible', timeout: 5_000 })
      .then(() => true)
      .catch(() => false)
    if (consentAppeared) {
      await page.keyboard.press('Tab')
      expect(await focusedElement(page)).toMatchObject({ tag: 'INPUT', type: 'checkbox' })
      await page.keyboard.press('Space')
      await expect(page.getByRole('checkbox')).toBeChecked()
    }
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: /continue/i })
    await page.keyboard.press('Enter')

    // Step 7: Training goal
    await expectFocusedHeading(page, /^training goal$/i)
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'SELECT' })
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'TEXTAREA' })
    await page.keyboard.type('Adapt to company policy language.')
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'INPUT' })
    await expect(page.getByRole('button', { name: /get recommendation/i })).toBeEnabled({ timeout: 120_000 })
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: /get recommendation/i })
    await page.keyboard.press('Enter')

    // Step 8: Confirm training plan
    await expectFocusedHeading(page, /confirm training plan/i)
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: /approve/i })
    await page.keyboard.press('Enter')

    // Step 9: Preview
    await expectFocusedHeading(page, /^preview$/i)
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: /generate preview/i })
    await page.keyboard.press('Enter')

    await expect(page.getByRole('button', { name: /approve full run/i })).toBeVisible({ timeout: 180_000 })
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: /approve full run/i })
    await page.keyboard.press('Enter')

    // Step 9b: Run progress (no keyboard action needed, just wait for completion)
    await expectFocusedHeading(page, /run progress/i)
    await expect(page.getByRole('heading', { name: /export dataset/i })).toBeVisible({ timeout: 300_000 })

    // Step 10: Export
    await expectFocusedHeading(page, /export dataset/i)
    await page.keyboard.press('Tab')
    expect(await focusedElement(page)).toMatchObject({ tag: 'BUTTON', text: /download export/i })
    const [download] = await Promise.all([page.waitForEvent('download'), page.keyboard.press('Enter')])
    const out = path.join(fixtureDir, await download.suggestedFilename())
    await download.saveAs(out)
    expect(fs.statSync(out).size).toBeGreaterThan(100)
  })
})
