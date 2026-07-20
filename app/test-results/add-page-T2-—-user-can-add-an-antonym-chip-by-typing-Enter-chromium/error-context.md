# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: add-page.spec.ts >> T2 — user can add an antonym chip by typing + Enter
- Location: tests/add-page.spec.ts:230:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('[data-testid="antonyms-editor"]')
Expected: visible
Timeout: 3000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 3000ms
  - waiting for locator('[data-testid="antonyms-editor"]')

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
> 235 |   await expect(page.locator('[data-testid="antonyms-editor"]')).toBeVisible({ timeout: 3000 });
      |                                                                 ^ Error: expect(locator).toBeVisible() failed
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
```