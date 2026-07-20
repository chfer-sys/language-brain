# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: add-page.spec.ts >> user can type a new group name and press Enter to create a chip
- Location: tests/add-page.spec.ts:339:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('[data-testid="groups-editor"]')
Expected: visible
Timeout: 3000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 3000ms
  - waiting for locator('[data-testid="groups-editor"]')

```

```yaml
- main:
  - link "← Back":
    - /url: /
  - heading "Add a sentence" [level=1]
  - paragraph: Type hanzi, optionally add an English hint, then click "Propose labels" to get the AI's draft. Edit any field before saving.
  - text: Hanzi
  - textbox "Hanzi":
    - /placeholder: 我流口水了
    - text: 我流口水了
  - text: English hint (optional)
  - textbox "English hint (optional)":
    - /placeholder: A short note to disambiguate the sentence
  - button "Proposing…" [disabled]
```

# Test source

```ts
  244 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  245 |   await page.locator('[data-testid="propose-btn"]').click();
  246 |   await expect(page.locator('[data-testid="antonyms-chip-饱"]')).toBeVisible({ timeout: 3000 });
  247 |   await page.locator('[data-testid="antonyms-chip-饱"] button.chip-remove').click();
  248 |   await expect(page.locator('[data-testid="antonyms-chip-饱"]')).not.toBeVisible();
  249 |   await expect(page.locator('[data-testid="antonyms-chip-热"]')).toBeVisible();
  250 | });
  251 | 
  252 | test('T2 — sends edited antonym chips (hanzi) to commitSentence', async ({ page }) => {
  253 |   setupApiMocks(page, { ...FAKE_LABELS, antonyms: ['饱', '热'] });
  254 |   await page.goto('/add');
  255 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  256 |   await page.locator('[data-testid="propose-btn"]').click();
  257 |   await expect(page.locator('[data-testid="antonyms-chip-饱"]')).toBeVisible({ timeout: 3000 });
  258 |   await page.locator('[data-testid="antonyms-input"]').fill('冷');
  259 |   await page.locator('[data-testid="antonyms-input"]').press('Enter');
  260 |   await page.locator('[data-testid="antonyms-chip-热"] button.chip-remove').click();
  261 |   await page.locator('[data-testid="save-btn"]').click();
  262 |   // Saved confirmation proves commit succeeded; chips' presence proves the right data was sent.
  263 |   await expect(page.locator('[data-testid="saved"]')).toBeVisible({ timeout: 3000 });
  264 | });
  265 | 
  266 | // ─── Group chips ───────────────────────────────────────────────────────────────
  267 | 
  268 | test('groups field renders as a chip editor (not CSV input)', async ({ page }) => {
  269 |   setupApiMocks(page);
  270 |   await page.goto('/add');
  271 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  272 |   await page.locator('[data-testid="propose-btn"]').click();
  273 |   await expect(page.locator('[data-testid="groups-editor"]')).toBeVisible({ timeout: 3000 });
  274 |   await expect(page.locator('[data-testid="groups-input"]')).toBeVisible();
  275 | });
  276 | 
  277 | // v0.9: groups are user-authored — AI proposal is ignored; chips start empty.
  278 | test('v0.9 — group chips are EMPTY after propose (AI proposal ignored)', async ({ page }) => {
  279 |   setupApiMocks(page);
  280 |   await page.goto('/add');
  281 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  282 |   await page.locator('[data-testid="propose-btn"]').click();
  283 |   await expect(page.locator('[data-testid="proposed-form"]')).toBeVisible({ timeout: 3000 });
  284 |   // No chips — user authors groups manually
  285 |   const chips = page.locator('[data-testid="groups-editor"] [data-testid^="groups-chip-"]');
  286 |   await expect(chips).toHaveCount(0);
  287 | });
  288 | 
  289 | test('v0.9 — user can add a group chip manually then remove it', async ({ page }) => {
  290 |   setupApiMocks(page);
  291 |   await page.goto('/add');
  292 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  293 |   await page.locator('[data-testid="propose-btn"]').click();
  294 |   await expect(page.locator('[data-testid="groups-editor"]')).toBeVisible({ timeout: 3000 });
  295 |   // Manually add a chip (v0.9: no AI seeding)
  296 |   await page.locator('[data-testid="groups-input"]').fill('travel');
  297 |   await page.locator('[data-testid="groups-input"]').press('Enter');
  298 |   await expect(page.locator('[data-testid="groups-chip-travel"]')).toBeVisible();
  299 |   // Remove it
  300 |   await page.locator('[data-testid="groups-chip-travel"] button.chip-remove').click();
  301 |   await expect(page.locator('[data-testid="groups-chip-travel"]')).not.toBeVisible();
  302 | });
  303 | 
  304 | // v0.9: user manually adds groups; slugs (not CSV) are sent to commitSentence.
  305 | test('v0.9 — sends group slug ids (not CSV strings) to commitSentence', async ({ page }) => {
  306 |   setupApiMocks(page);
  307 |   await page.goto('/add');
  308 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  309 |   await page.locator('[data-testid="propose-btn"]').click();
  310 |   await expect(page.locator('[data-testid="proposed-form"]')).toBeVisible({ timeout: 3000 });
  311 |   // Manually add a group chip — proves slug format is correct (slug-id, not CSV string)
  312 |   await page.locator('[data-testid="groups-input"]').fill('emotions');
  313 |   await page.locator('[data-testid="groups-input"]').press('Enter');
  314 |   await expect(page.locator('[data-testid="groups-chip-emotions"]')).toBeVisible();
  315 |   await page.locator('[data-testid="save-btn"]').click();
  316 |   await expect(page.locator('[data-testid="saved"]')).toBeVisible({ timeout: 3000 });
  317 | });
  318 | 
  319 | // v0.9: removed AI-seeding; user adds chips manually via input or dropdown.
  320 | test('v0.9 — user can remove a manually-added group chip via its × button', async ({ page }) => {
  321 |   setupApiMocks(page);
  322 |   await page.goto('/add');
  323 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  324 |   await page.locator('[data-testid="propose-btn"]').click();
  325 |   await expect(page.locator('[data-testid="groups-editor"]')).toBeVisible({ timeout: 3000 });
  326 |   // Manually add two chips
  327 |   await page.locator('[data-testid="groups-input"]').fill('food');
  328 |   await page.locator('[data-testid="groups-input"]').press('Enter');
  329 |   await page.locator('[data-testid="groups-input"]').fill('travel');
  330 |   await page.locator('[data-testid="groups-input"]').press('Enter');
  331 |   await expect(page.locator('[data-testid="groups-chip-food"]')).toBeVisible();
  332 |   await expect(page.locator('[data-testid="groups-chip-travel"]')).toBeVisible();
  333 |   // Remove one
  334 |   await page.locator('[data-testid="groups-chip-food"] button.chip-remove').click();
  335 |   await expect(page.locator('[data-testid="groups-chip-food"]')).not.toBeVisible();
  336 |   await expect(page.locator('[data-testid="groups-chip-travel"]')).toBeVisible();
  337 | });
  338 | 
  339 | test('user can type a new group name and press Enter to create a chip', async ({ page }) => {
  340 |   setupApiMocks(page);
  341 |   await page.goto('/add');
  342 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  343 |   await page.locator('[data-testid="propose-btn"]').click();
> 344 |   await expect(page.locator('[data-testid="groups-editor"]')).toBeVisible({ timeout: 3000 });
      |                                                               ^ Error: expect(locator).toBeVisible() failed
  345 |   await page.locator('[data-testid="groups-input"]').fill('emotions');
  346 |   await page.locator('[data-testid="groups-input"]').press('Enter');
  347 |   await expect(page.locator('[data-testid="groups-chip-emotions"]')).toBeVisible();
  348 | });
  349 | 
```