# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: add-page.spec.ts >> AC25 — calls proposeLabels and renders editable fields on AI response
- Location: tests/add-page.spec.ts:66:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('[data-testid="proposed-form"]')
Expected: visible
Timeout: 3000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 3000ms
  - waiting for locator('[data-testid="proposed-form"]')

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
  1   | import { test, expect, type Page } from '@playwright/test';
  2   | 
  3   | // ─── Fake payloads ───────────────────────────────────────────────────────────
  4   | 
  5   | const FAKE_LABELS = {
  6   |   pinyin: 'wǒ liú kǒu shuǐ le',
  7   |   english: "I'm drooling",
  8   |   meaning: 'visual craving: I see food and my mouth waters',
  9   |   words: ['我', '流', '口水', '了'],
  10  |   word_refs: ['wǒ', 'liú', 'kǒushuǐ', 'le'],
  11  |   groups: [
  12  |     { id: 'reactions', display_name: 'reactions', description: '' },
  13  |     { id: 'food', display_name: 'food', description: '' }
  14  |   ],
  15  |   antonyms: []
  16  | };
  17  | 
  18  | const FAKE_COMMIT_RESPONSE = {
  19  |   id: 'wo-liu-kou-shui-le',
  20  |   saved_at: '2026-06-27',
  21  |   word_ids_created: [],
  22  |   group_ids_created: []
  23  | };
  24  | 
  25  | const FAKE_SUGGEST: unknown[] = [];
  26  | 
  27  | // ─── Route setup ───────────────────────────────────────────────────────────────
  28  | // Use function URL matcher: url.href.includes(...) since url is a URL object.
  29  | 
  30  | function setupApiMocks(page: Page, proposePayload = FAKE_LABELS, commitPayload = FAKE_COMMIT_RESPONSE) {
  31  |   // GET /api/search/suggest — group autocomplete on mount
  32  |   page.route(/http:\/\/localhost:8000\/api\/search\/suggest/, (route) =>
  33  |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FAKE_SUGGEST) })
  34  |   );
  35  |   // POST /api/sentences — proposeLabels
  36  |   page.route(/http:\/\/localhost:8000\/api\/sentences$/, (route) => {
  37  |     // Only match POST (proposeLabels), not the commit endpoint
  38  |     if (route.request().method() !== 'POST') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  39  |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(proposePayload) });
  40  |   });
  41  |   // POST /api/sentences/commit
  42  |   page.route(/http:\/\/localhost:8000\/api\/sentences\/commit/, (route) => {
  43  |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(commitPayload) });
  44  |   });
  45  | }
  46  | 
  47  | // ─── AC25: Add-sentence page propose-labels flow ──────────────────────────────
  48  | 
  49  | test('AC25 — renders hanzi textarea, optional note, and Propose-labels button', async ({ page }) => {
  50  |   setupApiMocks(page);
  51  |   await page.goto('/add');
  52  |   await expect(page.locator('[data-testid="hanzi-input"]')).toBeVisible();
  53  |   await expect(page.locator('[data-testid="propose-btn"]')).toBeVisible();
  54  |   await expect(page.locator('input[type="text"]')).toBeVisible();
  55  | });
  56  | 
  57  | test('AC25 — Propose button is disabled when hanzi is empty', async ({ page }) => {
  58  |   setupApiMocks(page);
  59  |   await page.goto('/add');
  60  |   const btn = page.locator('[data-testid="propose-btn"]');
  61  |   await expect(btn).toBeDisabled();
  62  |   await page.locator('[data-testid="hanzi-input"]').fill('我');
  63  |   await expect(btn).toBeEnabled();
  64  | });
  65  | 
  66  | test('AC25 — calls proposeLabels and renders editable fields on AI response', async ({ page }) => {
  67  |   setupApiMocks(page);
  68  |   await page.goto('/add');
  69  |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  70  |   await page.locator('[data-testid="propose-btn"]').click();
> 71  |   await expect(page.locator('[data-testid="proposed-form"]')).toBeVisible({ timeout: 3000 });
      |                                                               ^ Error: expect(locator).toBeVisible() failed
  72  |   await expect(page.locator('[data-testid="pinyin-input"]')).toHaveValue(FAKE_LABELS.pinyin);
  73  |   const inputs = page.locator('[data-testid="proposed-form"] input');
  74  |   await expect(inputs).toHaveCount(7);
  75  | });
  76  | 
  77  | test('AC25 — passes English note to proposeLabels when user typed one', async ({ page }) => {
  78  |   setupApiMocks(page);
  79  |   await page.goto('/add');
  80  |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  81  |   await page.locator('input[type="text"]').first().fill('drooling over food');
  82  |   await page.locator('[data-testid="propose-btn"]').click();
  83  |   // The note value is sent to the backend; we verify the form was submitted.
  84  |   // The fact that proposed-form shows (not an error) proves the call succeeded.
  85  |   await expect(page.locator('[data-testid="proposed-form"]')).toBeVisible({ timeout: 3000 });
  86  | });
  87  | 
  88  | test('AC25 — user can edit a proposed field before saving', async ({ page }) => {
  89  |   setupApiMocks(page);
  90  |   await page.goto('/add');
  91  |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  92  |   await page.locator('[data-testid="propose-btn"]').click();
  93  |   await expect(page.locator('[data-testid="proposed-form"]')).toBeVisible({ timeout: 3000 });
  94  |   await page.locator('[data-testid="proposed-form"] input').nth(2).clear();
  95  |   await page.locator('[data-testid="proposed-form"] input').nth(2).fill('user-edited meaning');
  96  |   await page.locator('[data-testid="save-btn"]').click();
  97  |   await expect(page.locator('[data-testid="saved"]')).toBeVisible({ timeout: 3000 });
  98  | });
  99  | 
  100 | test('AC25 — renders Saved confirmation after commit succeeds', async ({ page }) => {
  101 |   setupApiMocks(page);
  102 |   await page.goto('/add');
  103 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  104 |   await page.locator('[data-testid="propose-btn"]').click();
  105 |   await expect(page.locator('[data-testid="proposed-form"]')).toBeVisible({ timeout: 3000 });
  106 |   await page.locator('[data-testid="save-btn"]').click();
  107 |   const saved = page.locator('[data-testid="saved"]');
  108 |   await expect(saved).toBeVisible({ timeout: 3000 });
  109 |   await expect(saved).toContainText('wo-liu-kou-shui-le');
  110 | });
  111 | 
  112 | test('AC25 — shows an error message if propose fails', async ({ page }) => {
  113 |   page.route(/http:\/\/localhost:8000\/api\/search\/suggest/, (route) =>
  114 |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  115 |   );
  116 |   page.route(/http:\/\/localhost:8000\/api\/sentences$/, (route) => {
  117 |     if (route.request().method() !== 'POST') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  118 |     route.fulfill({ status: 500, contentType: 'text/plain', body: 'AI provider unavailable' });
  119 |   });
  120 |   await page.goto('/add');
  121 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  122 |   await page.locator('[data-testid="propose-btn"]').click();
  123 |   await page.waitForTimeout(500);
  124 |   await expect(page.locator('.error')).toContainText('500');
  125 |   await expect(page.locator('[data-testid="proposed-form"]')).not.toBeVisible();
  126 | });
  127 | 
  128 | test('AC25 — Back link navigates to home page', async ({ page }) => {
  129 |   setupApiMocks(page);
  130 |   await page.goto('/add');
  131 |   const back = page.locator('a.back');
  132 |   await expect(back).toHaveAttribute('href', '/');
  133 | });
  134 | 
  135 | // ─── Note 1: English hint is authoritative ───────────────────────────────────
  136 | 
  137 | test('Note 1 — English field pre-filled from typed hint (authoritative)', async ({ page }) => {
  138 |   setupApiMocks(page);
  139 |   await page.goto('/add');
  140 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  141 |   await page.locator('input[type="text"]').first().fill('drooling over food');
  142 |   await page.locator('[data-testid="propose-btn"]').click();
  143 |   await expect(page.locator('[data-testid="english-input"]')).toHaveValue('drooling over food', { timeout: 3000 });
  144 |   await expect(page.locator('[data-testid="use-suggestion-btn"]')).toBeVisible();
  145 |   // Clicking the button populates the input with the AI draft (user can still edit it)
  146 |   await page.locator('[data-testid="use-suggestion-btn"]').click();
  147 |   await expect(page.locator('[data-testid="english-input"]')).toHaveValue(FAKE_LABELS.english);
  148 | });
  149 | 
  150 | test('Note 1 — sends user-edited English to commitSentence (not AI draft)', async ({ page }) => {
  151 |   setupApiMocks(page);
  152 |   await page.goto('/add');
  153 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  154 |   await page.locator('[data-testid="propose-btn"]').click();
  155 |   await expect(page.locator('[data-testid="proposed-form"]')).toBeVisible({ timeout: 3000 });
  156 |   await page.locator('[data-testid="english-input"]').clear();
  157 |   await page.locator('[data-testid="english-input"]').fill('final english I wrote');
  158 |   await page.locator('[data-testid="save-btn"]').click();
  159 |   // Saved confirmation proves the commit call succeeded.
  160 |   await expect(page.locator('[data-testid="saved"]')).toBeVisible({ timeout: 3000 });
  161 | });
  162 | 
  163 | test('Note 1 — hides AI suggestion when user matches AI draft', async ({ page }) => {
  164 |   setupApiMocks(page);
  165 |   await page.goto('/add');
  166 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  167 |   await page.locator('input[type="text"]').first().fill(FAKE_LABELS.english);
  168 |   await page.locator('[data-testid="propose-btn"]').click();
  169 |   await expect(page.locator('[data-testid="proposed-form"]')).toBeVisible({ timeout: 3000 });
  170 |   await expect(page.locator('[data-testid="use-suggestion-btn"]')).not.toBeVisible();
  171 | });
```