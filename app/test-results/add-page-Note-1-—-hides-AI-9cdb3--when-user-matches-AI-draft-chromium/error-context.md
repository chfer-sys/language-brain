# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: add-page.spec.ts >> Note 1 — hides AI suggestion when user matches AI draft
- Location: tests/add-page.spec.ts:163:1

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
    - text: I'm drooling
  - button "Proposing…" [disabled]
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
  69  |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  70  |   await page.locator('[data-testid="propose-btn"]').click();
  71  |   await expect(page.locator('[data-testid="proposed-form"]')).toBeVisible({ timeout: 3000 });
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
> 169 |   await expect(page.locator('[data-testid="proposed-form"]')).toBeVisible({ timeout: 3000 });
      |                                                               ^ Error: expect(locator).toBeVisible() failed
  170 |   await expect(page.locator('[data-testid="use-suggestion-btn"]')).not.toBeVisible();
  171 | });
  172 | 
  173 | test('Note 1 — click suggestion button populates English input when no hint given', async ({ page }) => {
  174 |   setupApiMocks(page);
  175 |   await page.goto('/add');
  176 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  177 |   // No English hint typed
  178 |   await page.locator('[data-testid="propose-btn"]').click();
  179 |   await expect(page.locator('[data-testid="proposed-form"]')).toBeVisible({ timeout: 3000 });
  180 |   // English input is empty (no hint was given)
  181 |   await expect(page.locator('[data-testid="english-input"]')).toHaveValue('');
  182 |   // Suggestion button is visible with the AI draft text
  183 |   await expect(page.locator('[data-testid="use-suggestion-btn"]')).toBeVisible();
  184 |   await expect(page.locator('[data-testid="use-suggestion-btn"]')).toContainText(FAKE_LABELS.english);
  185 |   // Clicking the button populates the English input
  186 |   await page.locator('[data-testid="use-suggestion-btn"]').click();
  187 |   await expect(page.locator('[data-testid="english-input"]')).toHaveValue(FAKE_LABELS.english);
  188 |   // Suggestion is still visible (user can revert by typing over)
  189 |   await expect(page.locator('[data-testid="use-suggestion-btn"]')).toBeVisible();
  190 | });
  191 | 
  192 | test('Note 1 — use-suggestion button reappears after user edits English to differ from proposed', async ({ page }) => {
  193 |   setupApiMocks(page);
  194 |   await page.goto('/add');
  195 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  196 |   // No English hint typed
  197 |   await page.locator('[data-testid="propose-btn"]').click();
  198 |   await expect(page.locator('[data-testid="proposed-form"]')).toBeVisible({ timeout: 3000 });
  199 |   // Clicking the button populates the English input with the AI draft
  200 |   await page.locator('[data-testid="use-suggestion-btn"]').click();
  201 |   await expect(page.locator('[data-testid="english-input"]')).toHaveValue(FAKE_LABELS.english);
  202 |   // Suggestion button is still visible (user can still revert)
  203 |   await expect(page.locator('[data-testid="use-suggestion-btn"]')).toBeVisible();
  204 |   // User edits the English field to a different value
  205 |   await page.locator('[data-testid="english-input"]').fill('user typed their own english');
  206 |   // Button reappears because english !== proposed.english
  207 |   await expect(page.locator('[data-testid="use-suggestion-btn"]')).toBeVisible();
  208 | });
  209 | 
  210 | // ─── T2 / Note 3: Antonym chip editor ────────────────────────────────────────
  211 | 
  212 | test('T2 — antonyms field renders as a chip editor (not CSV input)', async ({ page }) => {
  213 |   setupApiMocks(page);
  214 |   await page.goto('/add');
  215 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  216 |   await page.locator('[data-testid="propose-btn"]').click();
  217 |   await expect(page.locator('[data-testid="antonyms-editor"]')).toBeVisible({ timeout: 3000 });
  218 |   await expect(page.locator('[data-testid="antonyms-input"]')).toBeVisible();
  219 | });
  220 | 
  221 | test('T2 — seeds chip editor from AI proposed antonym hanzi', async ({ page }) => {
  222 |   setupApiMocks(page, { ...FAKE_LABELS, antonyms: ['饱', '热'] });
  223 |   await page.goto('/add');
  224 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  225 |   await page.locator('[data-testid="propose-btn"]').click();
  226 |   await expect(page.locator('[data-testid="antonyms-chip-饱"]')).toBeVisible({ timeout: 3000 });
  227 |   await expect(page.locator('[data-testid="antonyms-chip-热"]')).toBeVisible();
  228 | });
  229 | 
  230 | test('T2 — user can add an antonym chip by typing + Enter', async ({ page }) => {
  231 |   setupApiMocks(page);
  232 |   await page.goto('/add');
  233 |   await page.locator('[data-testid="hanzi-input"]').fill('我流口水了');
  234 |   await page.locator('[data-testid="propose-btn"]').click();
  235 |   await expect(page.locator('[data-testid="antonyms-editor"]')).toBeVisible({ timeout: 3000 });
  236 |   await page.locator('[data-testid="antonyms-input"]').fill('冷');
  237 |   await page.locator('[data-testid="antonyms-input"]').press('Enter');
  238 |   await expect(page.locator('[data-testid="antonyms-chip-冷"]')).toBeVisible();
  239 | });
  240 | 
  241 | test('T2 — user can remove an antonym chip via its × button', async ({ page }) => {
  242 |   setupApiMocks(page, { ...FAKE_LABELS, antonyms: ['饱', '热'] });
  243 |   await page.goto('/add');
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
```