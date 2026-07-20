# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: unit-detail.spec.ts >> click on connection navigates to that unit
- Location: tests/unit-detail.spec.ts:246:1

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
  191 |       { to: 'W6', kind: 'opposite', score: 1.0, name: '你' }
  192 |     ],
  193 |     created: '2026-07-01',
  194 |     updated: '2026-07-01',
  195 |     author_confirmed: true
  196 |   });
  197 |   await page.goto('/unit/W5');
  198 |   const link = page.locator('[data-testid="connections-kind-opposite"] a');
  199 |   await expect(link).toContainText('你');
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
> 291 |   await expect(page.locator('[data-testid="unit-properties"]')).toBeVisible();
      |                                                                 ^ Error: expect(locator).toBeVisible() failed
  292 |   // Verify URL is correct.
  293 |   await expect(page).toHaveURL(/\/unit\/s-1/);
  294 | 
  295 |   // Click the connection link to W5.
  296 |   await page.locator('[data-testid="connections-kind-opposite"] a').click();
  297 |   // Assert URL changed to W5.
  298 |   await expect(page).toHaveURL(/\/unit\/W5/);
  299 |   // Verify the new unit loaded (properties visible).
  300 |   await expect(page.locator('[data-testid="unit-properties"]')).toBeVisible();
  301 | });
  302 | 
```