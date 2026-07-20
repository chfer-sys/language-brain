# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: unit-edit.spec.ts >> word page shows Edit button
- Location: tests/unit-edit.spec.ts:159:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('[data-testid="edit-btn"]')
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for locator('[data-testid="edit-btn"]')

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
  62  |   },
  63  |   connections: [],
  64  |   created: '2026-06-27',
  65  |   updated: '2026-06-27',
  66  |   author_confirmed: true
  67  | };
  68  | 
  69  | // ─── Helpers ─────────────────────────────────────────────────────────────────
  70  | 
  71  | function mockUnit(page: Page, unit: unknown) {
  72  |   page.route(/http:\/\/localhost:8000\/api\/units\//, (route) =>
  73  |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(unit) })
  74  |   );
  75  |   page.route(/http:\/\/localhost:8000\/api\/pinyin\//, (route) =>
  76  |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  77  |   );
  78  |   // ponytail: suggest endpoint for existingGroups autocomplete in edit mode
  79  |   page.route(/http:\/\/localhost:8000\/api\/search\/suggest/, (route) =>
  80  |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  81  |   );
  82  | }
  83  | 
  84  | // ─── AC TBD: Sentence edit ────────────────────────────────────────────────────
  85  | 
  86  | test('sentence page shows Edit button', async ({ page }) => {
  87  |   mockUnit(page, FAKE_SENTENCE);
  88  |   await page.goto('/unit/s-1');
  89  |   await expect(page.locator('[data-testid="edit-btn"]')).toBeVisible();
  90  | });
  91  | 
  92  | test('sentence: clicking Edit shows form with fields pre-filled', async ({ page }) => {
  93  |   mockUnit(page, FAKE_SENTENCE);
  94  |   await page.goto('/unit/s-1');
  95  |   await page.locator('[data-testid="edit-btn"]').click();
  96  |   await expect(page.locator('[data-testid="edit-form"]')).toBeVisible();
  97  |   await expect(page.locator('[data-testid="edit-hanzi-display"]')).toContainText('我喜欢吃');
  98  |   await expect(page.locator('[data-testid="edit-pinyin"]')).toHaveValue('wǒ xǐhuān chī');
  99  |   await expect(page.locator('[data-testid="edit-english"]')).toHaveValue('I like to eat');
  100 |   await expect(page.locator('[data-testid="edit-meaning"]')).toHaveValue('expressing enjoyment of eating');
  101 |   // words is CSV
  102 |   await expect(page.locator('[data-testid="edit-words"]')).toHaveValue('我, 喜欢, 吃');
  103 |   await expect(page.locator('[data-testid="save-edit-btn"]')).toBeVisible();
  104 |   await expect(page.locator('[data-testid="cancel-edit-btn"]')).toBeVisible();
  105 | });
  106 | 
  107 | test('sentence: Save calls PUT /api/sentences/{id} with correct body', async ({ page }) => {
  108 |   let savedBody: Record<string, unknown> | null = null;
  109 |   page.route(/http:\/\/localhost:8000\/api\/sentences\/s-1/, (route) => {
  110 |     if (route.request().method() === 'PUT') {
  111 |       savedBody = route.request().postData() ? JSON.parse(route.request().postData()!) : null;
  112 |     }
  113 |     route.fulfill({
  114 |       status: 200,
  115 |       contentType: 'application/json',
  116 |       body: JSON.stringify({ id: 's-1', updated: '2026-07-21', connections_summary: {}, groups_added: [], groups_removed: [] })
  117 |     });
  118 |   });
  119 |   page.route(/http:\/\/localhost:8000\/api\/units\/s-1/, (route) =>
  120 |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FAKE_SENTENCE) })
  121 |   );
  122 |   page.route(/http:\/\/localhost:8000\/api\/pinyin\//, (route) =>
  123 |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  124 |   );
  125 |   page.route(/http:\/\/localhost:8000\/api\/search\/suggest/, (route) =>
  126 |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  127 |   );
  128 | 
  129 |   await page.goto('/unit/s-1');
  130 |   await page.locator('[data-testid="edit-btn"]').click();
  131 |   await page.locator('[data-testid="edit-english"]').fill('I really like to eat');
  132 |   await page.locator('[data-testid="save-edit-btn"]').click();
  133 |   await page.waitForTimeout(500);
  134 | 
  135 |   expect(savedBody).not.toBeNull();
  136 |   expect(savedBody!['hanzi']).toBe('我喜欢吃');
  137 |   expect(savedBody!['english']).toBe('I really like to eat');
  138 |   expect(savedBody!['pinyin']).toBe('wǒ xǐhuān chī');
  139 |   expect(savedBody!['words']).toEqual(['我', '喜欢', '吃']);
  140 | });
  141 | 
  142 | test('sentence: Cancel hides form without calling any endpoint', async ({ page }) => {
  143 |   let anyPut = false;
  144 |   page.route(/http:\/\/localhost:8000\/api\/sentences\//, (route) => {
  145 |     if (route.request().method() === 'PUT') anyPut = true;
  146 |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  147 |   });
  148 |   mockUnit(page, FAKE_SENTENCE);
  149 |   await page.goto('/unit/s-1');
  150 |   await page.locator('[data-testid="edit-btn"]').click();
  151 |   await page.locator('[data-testid="edit-english"]').fill('changed');
  152 |   await page.locator('[data-testid="cancel-edit-btn"]').click();
  153 |   await expect(page.locator('[data-testid="edit-form"]')).not.toBeVisible();
  154 |   expect(anyPut).toBe(false);
  155 | });
  156 | 
  157 | // ─── Word edit ────────────────────────────────────────────────────────────────
  158 | 
  159 | test('word page shows Edit button', async ({ page }) => {
  160 |   mockUnit(page, FAKE_WORD);
  161 |   await page.goto('/unit/chī');
> 162 |   await expect(page.locator('[data-testid="edit-btn"]')).toBeVisible();
      |                                                          ^ Error: expect(locator).toBeVisible() failed
  163 | });
  164 | 
  165 | test('word: clicking Edit shows form with fields pre-filled', async ({ page }) => {
  166 |   mockUnit(page, FAKE_WORD);
  167 |   await page.goto('/unit/chī');
  168 |   await page.locator('[data-testid="edit-btn"]').click();
  169 |   await expect(page.locator('[data-testid="edit-form"]')).toBeVisible();
  170 |   await expect(page.locator('[data-testid="edit-english"]')).toHaveValue('to eat');
  171 |   await expect(page.locator('[data-testid="edit-meaning"]')).toHaveValue('the act of eating');
  172 |   await expect(page.locator('[data-testid="save-edit-btn"]')).toBeVisible();
  173 |   await expect(page.locator('[data-testid="cancel-edit-btn"]')).toBeVisible();
  174 | });
  175 | 
  176 | // ─── Compound edit ────────────────────────────────────────────────────────────
  177 | 
  178 | test('compound page shows Edit button', async ({ page }) => {
  179 |   mockUnit(page, FAKE_COMPOUND);
  180 |   await page.goto('/unit/c-1');
  181 |   await expect(page.locator('[data-testid="edit-btn"]')).toBeVisible();
  182 | });
  183 | 
  184 | test('compound: clicking Edit shows form with same fields as word', async ({ page }) => {
  185 |   mockUnit(page, FAKE_COMPOUND);
  186 |   await page.goto('/unit/c-1');
  187 |   await page.locator('[data-testid="edit-btn"]').click();
  188 |   await expect(page.locator('[data-testid="edit-form"]')).toBeVisible();
  189 |   // compound form has english, meaning, groups, antonyms — same as word
  190 |   await expect(page.locator('[data-testid="edit-english"]')).toHaveValue('to have a meal');
  191 |   await expect(page.locator('[data-testid="edit-meaning"]')).toHaveValue('the act of eating rice / having a meal');
  192 |   await expect(page.locator('[data-testid="save-edit-btn"]')).toBeVisible();
  193 |   await expect(page.locator('[data-testid="cancel-edit-btn"]')).toBeVisible();
  194 | });
  195 | 
```