# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: unit-detail.spec.ts >> connections render name when present
- Location: tests/unit-detail.spec.ts:183:1

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: locator('[data-testid="connections-kind-opposite"] a')
Expected substring: "你"
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toContainText" with timeout 5000ms
  - waiting for locator('[data-testid="connections-kind-opposite"] a')

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
  99  | 
  100 | test('AC26 — renders groups as read-only chips, not CSV text', async ({ page }) => {
  101 |   mockUnitApi(page, FAKE_SENTENCE);
  102 |   await page.goto('/unit/s-1');
  103 |   // Use .first() since there may be multiple chips-readonly elements
  104 |   const chipsReadonly = page.locator('.chips-readonly').first();
  105 |   await expect(chipsReadonly).toBeVisible();
  106 |   const groupChip = page.locator('[data-testid="prop-groups-chip-food"]');
  107 |   await expect(groupChip).toBeVisible();
  108 |   await expect(groupChip).toContainText('food');
  109 |   const props = page.locator('[data-testid="unit-properties"]');
  110 |   await expect(props).not.toContainText('food,');
  111 |   await expect(props).not.toContainText(', food');
  112 | });
  113 | 
  114 | test('AC26 — groups connections by kind with a section per kind', async ({ page }) => {
  115 |   mockUnitApi(page, FAKE_SENTENCE);
  116 |   await page.goto('/unit/s-1');
  117 |   const lexSection = page.locator('[data-testid="connections-kind-lexical"]');
  118 |   const groupSection = page.locator('[data-testid="connections-kind-group"]');
  119 |   const semSection = page.locator('[data-testid="connections-kind-semantic"]');
  120 |   await expect(lexSection).toBeVisible();
  121 |   await expect(groupSection).toBeVisible();
  122 |   await expect(semSection).not.toBeVisible();
  123 |   await expect(lexSection).toContainText('chī');
  124 |   await expect(lexSection).toContainText('xǐhuān');
  125 |   await expect(groupSection).toContainText('food');
  126 | });
  127 | 
  128 | test('AC26 — word unit renders opposite-kind section', async ({ page }) => {
  129 |   mockUnitApi(page, FAKE_WORD);
  130 |   await page.goto('/unit/chī');
  131 |   await expect(page.locator('[data-testid="unit-type"]')).toContainText('word');
  132 |   const oppSection = page.locator('[data-testid="connections-kind-opposite"]');
  133 |   await expect(oppSection).toContainText('饿');
  134 | });
  135 | 
  136 | // ─── AC27: Word page lists containing sentences ───────────────────────────────
  137 | 
  138 | test('AC27 — word page lists containing sentences with links', async ({ page }) => {
  139 |   mockUnitApi(page, FAKE_WORD);
  140 |   await page.goto('/unit/chī');
  141 |   const section = page.locator('[data-testid="containing-sentences"]');
  142 |   await expect(section).toBeVisible();
  143 |   await expect(section).toContainText('Sentences containing this word');
  144 |   const links = section.locator('a[href^="/unit/"]');
  145 |   await expect(links).toHaveCount(2);
  146 |   await expect(links.nth(0)).toHaveAttribute('href', '/unit/s-1');
  147 |   await expect(links.nth(1)).toHaveAttribute('href', '/unit/wo-xihuan-chi');
  148 | });
  149 | 
  150 | test('AC27 — word page shows empty-state when no sentences contain it', async ({ page }) => {
  151 |   mockUnitApi(page, FAKE_WORD_NO_SENTENCES);
  152 |   await page.goto('/unit/lí');
  153 |   const section = page.locator('[data-testid="containing-sentences"]');
  154 |   await expect(section).toBeVisible();
  155 |   await expect(section.locator('[data-testid="no-containing"]')).toContainText(/not yet referenced/i);
  156 | });
  157 | 
  158 | test('AC27 — sentence and group pages do NOT show containing-sentences section', async ({ page }) => {
  159 |   mockUnitApi(page, FAKE_SENTENCE);
  160 |   await page.goto('/unit/s-1');
  161 |   await expect(page.locator('[data-testid="containing-sentences"]')).not.toBeVisible();
  162 | });
  163 | 
  164 | // ─── Error & navigation ────────────────────────────────────────────────────────
  165 | 
  166 | test('shows error message when getUnit fails', async ({ page }) => {
  167 |   mockUnitApiError(page, 'does-not-exist');
  168 |   await page.goto('/unit/does-not-exist');
  169 |   const errorEl = page.locator('.error');
  170 |   await expect(errorEl).toBeVisible();
  171 |   await expect(errorEl).toContainText('does-not-exist');
  172 | });
  173 | 
  174 | test('has a back link to the home page', async ({ page }) => {
  175 |   mockUnitApi(page, FAKE_SENTENCE);
  176 |   await page.goto('/unit/s-1');
  177 |   const back = page.locator('[data-testid="back-link"]');
  178 |   await expect(back).toBeVisible();
  179 | });
  180 | 
  181 | // ─── Connection + containing-sentence name enrichment ─────────────────────────
  182 | 
  183 | test('connections render name when present', async ({ page }) => {
  184 |   // Mock a unit whose connections carry the name field.
  185 |   mockUnitApi(page, {
  186 |     id: 'W5',
  187 |     type: 'word',
  188 |     name: '我',
  189 |     properties: { hanzi: '我', pinyin: 'wǒ', english: 'I/me', meaning: '', groups: [], antonyms: [] },
  190 |     connections: [
  191 |       { to: 'W6', kind: 'opposite', score: 1.0, name: '你' }
  192 |     ],
  193 |     created: '2026-07-01',
  194 |     updated: '2026-07-01',
  195 |     author_confirmed: true
  196 |   });
  197 |   await page.goto('/unit/W5');
  198 |   const link = page.locator('[data-testid="connections-kind-opposite"] a');
> 199 |   await expect(link).toContainText('你');
      |                      ^ Error: expect(locator).toContainText(expected) failed
  200 |   await expect(link).not.toContainText('W6');
  201 | });
  202 | 
  203 | test('connections fall back to id when name missing', async ({ page }) => {
  204 |   // Mock a unit whose connections have no name field (legacy shape).
  205 |   mockUnitApi(page, {
  206 |     id: 'W5',
  207 |     type: 'word',
  208 |     name: '我',
  209 |     properties: { hanzi: '我', pinyin: 'wǒ', english: 'I/me', meaning: '', groups: [], antonyms: [] },
  210 |     connections: [
  211 |       { to: 'W6', kind: 'opposite', score: 1.0 }
  212 |     ],
  213 |     created: '2026-07-01',
  214 |     updated: '2026-07-01',
  215 |     author_confirmed: true
  216 |   });
  217 |   await page.goto('/unit/W5');
  218 |   const link = page.locator('[data-testid="connections-kind-opposite"] a');
  219 |   // Falls back to bare id.
  220 |   await expect(link).toContainText('W6');
  221 | });
  222 | 
  223 | test('containing sentences render sentence name', async ({ page }) => {
  224 |   mockUnitApi(page, {
  225 |     id: 'W5',
  226 |     type: 'word',
  227 |     name: '我',
  228 |     properties: { hanzi: '我', pinyin: 'wǒ', english: 'I/me', meaning: '', groups: [], antonyms: [] },
  229 |     connections: [],
  230 |     containing_sentences: [
  231 |       { id: 'S1', name: '我喜欢吃' },
  232 |       { id: 'S2', name: '我是学生' }
  233 |     ],
  234 |     created: '2026-07-01',
  235 |     updated: '2026-07-01',
  236 |     author_confirmed: true
  237 |   });
  238 |   await page.goto('/unit/W5');
  239 |   const section = page.locator('[data-testid="containing-sentences"]');
  240 |   const links = section.locator('a');
  241 |   await expect(links).toHaveCount(2);
  242 |   await expect(links.nth(0)).toContainText('我喜欢吃');
  243 |   await expect(links.nth(1)).toContainText('我是学生');
  244 | });
  245 | 
  246 | test('click on connection navigates to that unit', async ({ page }) => {
  247 |   // Mock two units: s-1 (sentence) and W5 (word).
  248 |   // Uses a Map-based mock to return different units per id.
  249 |   const units = new Map<string, unknown>();
  250 |   units.set('s-1', {
  251 |     id: 's-1',
  252 |     type: 'sentence',
  253 |     name: '我喜欢吃',
  254 |     properties: {
  255 |       hanzi: '我喜欢吃', pinyin: 'wǒ xǐhuān chī', english: 'I like to eat',
  256 |       meaning: '', words: ['我', '喜欢', '吃'], word_refs: ['wǒ', 'xǐhuān', 'chī'],
  257 |       groups: [], antonyms: []
  258 |     },
  259 |     connections: [{ to: 'W5', kind: 'opposite', score: 1.0, name: '我' }],
  260 |     created: '2026-07-01', updated: '2026-07-01', author_confirmed: true
  261 |   });
  262 |   units.set('W5', {
  263 |     id: 'W5',
  264 |     type: 'word',
  265 |     name: '我',
  266 |     properties: {
  267 |       hanzi: '我', pinyin: 'wǒ', english: 'I/me', meaning: '',
  268 |       groups: [], antonyms: []
  269 |     },
  270 |     connections: [],
  271 |     created: '2026-07-01', updated: '2026-07-01', author_confirmed: true
  272 |   });
  273 |   // Intercept /api/units/ by extracting the id from the URL path.
  274 |   page.route(/\/api\/units\/(.+)/, (route) => {
  275 |     const url = new URL(route.request().url());
  276 |     const id = decodeURIComponent(url.pathname.replace('/api/units/', ''));
  277 |     const unit = units.get(id);
  278 |     if (unit) {
  279 |       route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(unit) });
  280 |     } else {
  281 |       route.fulfill({ status: 404, contentType: 'text/plain', body: `unit ${id} not found` });
  282 |     }
  283 |   });
  284 |   // Also intercept pinyin so HanziWithPinyin resolves without errors.
  285 |   page.route(/\/api\/pinyin\/(.+)/, (route) =>
  286 |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  287 |   );
  288 | 
  289 |   await page.goto('/unit/s-1');
  290 |   // Wait for the unit properties section to confirm the page loaded.
  291 |   await expect(page.locator('[data-testid="unit-properties"]')).toBeVisible();
  292 |   // Verify URL is correct.
  293 |   await expect(page).toHaveURL(/\/unit\/s-1/);
  294 | 
  295 |   // Click the connection link to W5.
  296 |   await page.locator('[data-testid="connections-kind-opposite"] a').click();
  297 |   // Assert URL changed to W5.
  298 |   await expect(page).toHaveURL(/\/unit\/W5/);
  299 |   // Verify the new unit loaded (properties visible).
```