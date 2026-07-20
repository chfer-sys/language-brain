# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: unit-detail.spec.ts >> AC26 — renders groups as read-only chips, not CSV text
- Location: tests/unit-detail.spec.ts:100:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('.chips-readonly').first()
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for locator('.chips-readonly').first()

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
  5   | const FAKE_SENTENCE = {
  6   |   id: 's-1',
  7   |   type: 'sentence',
  8   |   name: '我喜欢吃',
  9   |   properties: {
  10  |     hanzi: '我喜欢吃',
  11  |     pinyin: 'wǒ xǐhuān chī',
  12  |     english: 'I like to eat',
  13  |     meaning: 'expressing enjoyment of eating',
  14  |     words: ['我', '喜欢', '吃'],
  15  |     word_refs: ['wǒ', 'xǐhuān', 'chī'],
  16  |     groups: ['food'],
  17  |     antonyms: []
  18  |   },
  19  |   connections: [
  20  |     { to: 'chī', kind: 'lexical', score: 1.0 },
  21  |     { to: 'food', kind: 'group', score: 1.0 },
  22  |     { to: 'xǐhuān', kind: 'lexical', score: 0.67 }
  23  |   ],
  24  |   created: '2026-06-27',
  25  |   updated: '2026-06-27',
  26  |   author_confirmed: true
  27  | };
  28  | 
  29  | const FAKE_WORD = {
  30  |   id: 'chī',
  31  |   type: 'word',
  32  |   name: '吃',
  33  |   properties: {
  34  |     hanzi: '吃',
  35  |     pinyin: 'chī',
  36  |     english: 'to eat',
  37  |     meaning: 'the act of eating',
  38  |     groups: ['food'],
  39  |     antonyms: ['饿']
  40  |   },
  41  |   connections: [
  42  |     { to: 's-1', kind: 'lexical', score: 1.0, name: '我喜欢吃' },
  43  |     { to: '饿', kind: 'opposite', score: 1.0, name: '饿' }
  44  |   ],
  45  |   containing_sentences: [{ id: 's-1', name: '我喜欢吃' }, { id: 'wo-xihuan-chi', name: '我喜欢吃和' }],
  46  |   created: '2026-06-27',
  47  |   updated: '2026-06-27',
  48  |   author_confirmed: true
  49  | };
  50  | 
  51  | const FAKE_WORD_NO_SENTENCES = {
  52  |   ...FAKE_WORD,
  53  |   id: 'lí',
  54  |   name: '离',
  55  |   containing_sentences: []
  56  | };
  57  | 
  58  | // ─── Helpers ─────────────────────────────────────────────────────────────────
  59  | 
  60  | function mockUnitApi(page: Page, unit: unknown) {
  61  |   // getUnit calls /api/units/{id}. Also mock /api/pinyin for HanziWithPinyin.
  62  |   page.route(/http:\/\/localhost:8000\/api\/units\//, (route) =>
  63  |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(unit) })
  64  |   );
  65  |   page.route(/http:\/\/localhost:8000\/api\/pinyin\//, (route) =>
  66  |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  67  |   );
  68  | }
  69  | 
  70  | function mockUnitApiError(page: Page, id: string) {
  71  |   page.route(new RegExp(`http://localhost:8000/api/units/${id}`), (route) =>
  72  |     route.fulfill({ status: 404, contentType: 'text/plain', body: `unit ${id} not found` })
  73  |   );
  74  |   page.route(/http:\/\/localhost:8000\/api\/pinyin\//, (route) =>
  75  |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  76  |   );
  77  | }
  78  | 
  79  | // ─── AC26: Unit detail page ───────────────────────────────────────────────────
  80  | 
  81  | test('AC26 — reads page.params.id and calls getUnit with it', async ({ page }) => {
  82  |   mockUnitApi(page, FAKE_SENTENCE);
  83  |   await page.goto('/unit/s-1');
  84  |   // Verify unit loaded via properties (hanzi in properties is always visible;
  85  |   // HanziWithPinyin text is async-loaded and tested separately in T4.)
  86  |   await expect(page.locator('[data-testid="unit-properties"]')).toContainText('我喜欢吃');
  87  |   await expect(page.locator('[data-testid="unit-type"]')).toContainText('sentence');
  88  | });
  89  | 
  90  | test('AC26 — shows unit properties (hanzi, pinyin, english, meaning)', async ({ page }) => {
  91  |   mockUnitApi(page, FAKE_SENTENCE);
  92  |   await page.goto('/unit/s-1');
  93  |   const props = page.locator('[data-testid="unit-properties"]');
  94  |   await expect(props).toContainText('我喜欢吃');
  95  |   await expect(props).toContainText('wǒ xǐhuān chī');
  96  |   await expect(props).toContainText('I like to eat');
  97  |   await expect(props).toContainText('expressing enjoyment of eating');
  98  | });
  99  | 
  100 | test('AC26 — renders groups as read-only chips, not CSV text', async ({ page }) => {
  101 |   mockUnitApi(page, FAKE_SENTENCE);
  102 |   await page.goto('/unit/s-1');
  103 |   // Use .first() since there may be multiple chips-readonly elements
  104 |   const chipsReadonly = page.locator('.chips-readonly').first();
> 105 |   await expect(chipsReadonly).toBeVisible();
      |                               ^ Error: expect(locator).toBeVisible() failed
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
  199 |   await expect(link).toContainText('你');
  200 |   await expect(link).not.toContainText('W6');
  201 | });
  202 | 
  203 | test('connections fall back to id when name missing', async ({ page }) => {
  204 |   // Mock a unit whose connections have no name field (legacy shape).
  205 |   mockUnitApi(page, {
```