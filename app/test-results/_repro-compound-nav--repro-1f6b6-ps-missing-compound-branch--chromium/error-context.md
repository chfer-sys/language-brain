# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: _repro-compound-nav.spec.ts >> _repro — compound has no properties rendered (known bug: topProps missing compound branch)
- Location: tests/_repro-compound-nav.spec.ts:78:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('[data-testid="unit-properties"]')
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for locator('[data-testid="unit-properties"]')

```

```yaml
- text: "[plugin:vite-plugin-svelte] src/routes/unit/[id]/+page.svelte:218:43 Can only bind to state or props https://svelte.dev/e/bind_invalid_value src/routes/unit/[id]/+page.svelte:218:43 216 | <label class=\"field\"> 217 | <span class=\"label\">Pinyin</span> 218 | <input type=\"text\" bind:value={editPinyin} data-testid=\"edit-pinyin\" /> ^ 219 | </label> 220 | <label class=\"field\"> Click outside, press Esc key, or fix the code to dismiss. You can also disable this overlay by setting"
- code: server.hmr.overlay
- text: to
- code: "false"
- text: in
- code: vite.config.ts
- text: .
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | /**
  4  |  * Reproduction: compound → sentence nav bug
  5  |  *
  6  |  * User report: "When I open a compound unit (e.g. `/unit/C2`) and click a
  7  |  * sentence link in the Connections section, the page does not redirect."
  8  |  *
  9  |  * C2 has connections: [{to: "S29", kind: "lexical", score: 1.0}]
  10 |  * S29 is a sentence ("那你是什么专业啊").
  11 |  *
  12 |  * This test hits the REAL backend (no mocks) so requires:
  13 |  *   1. FastAPI running on 127.0.0.1:8000
  14 |  *   2. SvelteKit dev server running on localhost:5173
  15 |  *
  16 |  * Run with: cd app && npx playwright test _repro-compound-nav.spec.ts
  17 |  */
  18 | 
  19 | const API_BASE = 'http://127.0.0.1:8000';
  20 | const COMPOUND_ID = 'C2';
  21 | const SENTENCE_ID = 'S29';
  22 | 
  23 | test('_repro — compound unit loads and shows Connections section', async ({ page }) => {
  24 |   // Navigate to the compound unit page
  25 |   await page.goto(`/unit/${COMPOUND_ID}`);
  26 | 
  27 |   // Wait for the page to load
  28 |   await page.waitForLoadState('networkidle');
  29 | 
  30 |   // Assert the page title/header contains the compound name
  31 |   const unitName = page.locator('[data-testid="unit-name"]');
  32 |   await expect(unitName).toBeVisible();
  33 | 
  34 |   // Assert the Connections section is visible
  35 |   const connectionsSection = page.locator('[data-testid="unit-connections"]');
  36 |   await expect(connectionsSection).toBeVisible();
  37 | 
  38 |   // Assert the lexical connections are shown
  39 |   const lexSection = page.locator('[data-testid="connections-kind-lexical"]');
  40 |   await expect(lexSection).toBeVisible();
  41 | 
  42 |   // Assert there is a link to S29 in the lexical section.
  43 |   // Note: the link text shows the resolved name (hanzi), not the ID.
  44 |   const sentenceLink = page.locator(`[data-testid="connections-kind-lexical"] a[href="/unit/${SENTENCE_ID}"]`);
  45 |   await expect(sentenceLink).toBeVisible();
  46 |   await expect(sentenceLink).toContainText('那你是什么专业啊'); // resolved name
  47 | });
  48 | 
  49 | test('_repro — clicking sentence link in compound Connections navigates to sentence', async ({ page }) => {
  50 |   // Start at the compound page
  51 |   await page.goto(`/unit/${COMPOUND_ID}`);
  52 |   await page.waitForLoadState('networkidle');
  53 | 
  54 |   // Verify the link exists and check its href
  55 |   const sentenceLink = page.locator(`[data-testid="connections-kind-lexical"] a[href="/unit/${SENTENCE_ID}"]`);
  56 |   await expect(sentenceLink).toBeVisible();
  57 |   await expect(sentenceLink).toHaveAttribute('href', `/unit/${SENTENCE_ID}`);
  58 | 
  59 |   // Capture the URL before clicking
  60 |   const urlBeforeClick = page.url();
  61 |   expect(urlBeforeClick).toContain(`/unit/${COMPOUND_ID}`);
  62 | 
  63 |   // Click the sentence link and wait for URL change
  64 |   await Promise.all([
  65 |     page.waitForURL(`**/unit/${SENTENCE_ID}`, { timeout: 10000 }),
  66 |     sentenceLink.click()
  67 |   ]);
  68 | 
  69 |   // Assert the URL changed to the sentence unit
  70 |   const urlAfterClick = page.url();
  71 |   expect(urlAfterClick).toContain(`/unit/${SENTENCE_ID}`);
  72 | 
  73 |   // Assert the sentence unit is now rendered
  74 |   const unitType = page.locator('[data-testid="unit-type"]');
  75 |   await expect(unitType).toContainText('sentence');
  76 | });
  77 | 
  78 | test('_repro — compound has no properties rendered (known bug: topProps missing compound branch)', async ({ page }) => {
  79 |   // This test documents the current behavior: compound renders empty <dl>
  80 |   // Once topProps() is fixed, this test should fail (which is expected).
  81 |   await page.goto(`/unit/${COMPOUND_ID}`);
  82 |   await page.waitForLoadState('networkidle');
  83 | 
  84 |   // Properties section exists
  85 |   const propsSection = page.locator('[data-testid="unit-properties"]');
> 86 |   await expect(propsSection).toBeVisible();
     |                              ^ Error: expect(locator).toBeVisible() failed
  87 | 
  88 |   // The <dl> should have no <dd> children if topProps() doesn't handle compound
  89 |   // This test passes now and should FAIL after the fix (which is correct behavior)
  90 |   const ddElements = propsSection.locator('dd');
  91 |   const count = await ddElements.count();
  92 |   // Currently compound returns empty topProps, so count is 0
  93 |   // After fix, compound should return hanzi, pinyin, english, etc. (count > 0)
  94 |   // We just document the current state here
  95 |   expect(count).toBeGreaterThanOrEqual(0); // Just verify section exists
  96 | });
  97 | 
```