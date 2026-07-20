# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: default-page.spec.ts >> AC24 — clicking a kind-toggle updates result pane without page reload
- Location: tests/default-page.spec.ts:85:1

# Error details

```
Error: expect(received).toBeGreaterThan(expected)

Expected: > 1
Received:   0
```

# Page snapshot

```yaml
- generic [ref=e2]:
  - generic [ref=e3]:
    - banner [ref=e4]:
      - heading "Language Brain" [level=1] [ref=e5]
      - paragraph [ref=e6]: 语言大脑
    - 'searchbox "Try: 看起来好吃 or 吃 or basic-verbs" [ref=e8]': 吃
    - navigation "Primary" [ref=e9]:
      - link "Browse vault" [ref=e10] [cursor=pointer]:
        - /url: /vault
      - link "+ Add sentence" [ref=e11] [cursor=pointer]:
        - /url: /add
  - generic [ref=e12]:
    - group "Connection-kind filters" [ref=e13]:
      - generic [ref=e14]: kind
      - button "lex" [active] [ref=e15] [cursor=pointer]
      - button "sem" [pressed] [ref=e16] [cursor=pointer]
      - button "grp" [pressed] [ref=e17] [cursor=pointer]
      - button "opp" [pressed] [ref=e18] [cursor=pointer]
    - group "Unit-type filters" [ref=e19]:
      - generic [ref=e20]: type
      - button "sent" [pressed] [ref=e21] [cursor=pointer]
      - button "words" [pressed] [ref=e22] [cursor=pointer]
      - button "cmpd" [pressed] [ref=e23] [cursor=pointer]
      - button "groups" [pressed] [ref=e24] [cursor=pointer]
  - region "Search results" [ref=e25]:
    - paragraph [ref=e26]: Searching…
```

# Test source

```ts
  5   | const FAKE_RESULTS = [
  6   |   { id: 'chī', type: 'word', name: '吃', snippet: 'chī', kinds: ['lexical'], score: 1.0 },
  7   |   { id: 'chīfàn', type: 'word', name: '吃饭', snippet: 'chīfàn', kinds: ['lexical'], score: 0.5 },
  8   |   { id: 's-1', type: 'sentence', name: '我喜欢吃', snippet: 'wǒ xǐhuān chī', kinds: ['lexical'], score: 0.25 }
  9   | ];
  10  | 
  11  | // Route pattern matches the absolute API URL (app calls http://localhost:8000/api/search,
  12  | // not the same-origin /api/search path). Uses absolute URL regex like other passing tests.
  13  | const SEARCH_ROUTE = /http:\/\/localhost:8000\/api\/search/;
  14  | 
  15  | async function typeSearch(page: Page, text: string) {
  16  |   const input = page.locator('input[type="search"]');
  17  |   await input.click();
  18  |   await page.waitForTimeout(100);
  19  |   await page.keyboard.type(text);
  20  |   await page.waitForTimeout(50); // let event propagate
  21  | }
  22  | 
  23  | // ─── AC22: default page renders a search box ──────────────────────────────────
  24  | 
  25  | test('AC22 — renders a search input as the primary above-the-fold control', async ({ page }) => {
  26  |   await page.route(SEARCH_ROUTE, (route) =>
  27  |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ query: '', results: [] }) })
  28  |   );
  29  |   await page.goto('/');
  30  |   await expect(page.locator('input[type="search"]')).toBeVisible();
  31  | });
  32  | 
  33  | // ─── AC23: search debounce 200ms ─────────────────────────────────────────────
  34  | 
  35  | test('AC23 — does not call search immediately on keystroke', async ({ page }) => {
  36  |   let searchHit = false;
  37  |   page.on('request', (req) => { if (req.url().includes('/api/search')) searchHit = true; });
  38  |   await page.route(SEARCH_ROUTE, (route) =>
  39  |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ query: '', results: FAKE_RESULTS }) })
  40  |   );
  41  |   await page.goto('/');
  42  |   await typeSearch(page, '吃');
  43  |   await page.waitForTimeout(50);
  44  |   expect(searchHit).toBe(false);
  45  | });
  46  | 
  47  | // AC23: Debounce verification — verify results appear after typing stops.
  48  | // The exact timing (200ms debounce) requires fake timers which E2E doesn't support.
  49  | test('AC23 — results appear after debounce delay', async ({ page }) => {
  50  |   await page.route(SEARCH_ROUTE, (route) =>
  51  |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ query: '吃', results: FAKE_RESULTS }) })
  52  |   );
  53  |   await page.goto('/');
  54  |   await page.waitForLoadState('networkidle');
  55  |   await typeSearch(page, '吃');
  56  |   // Wait for debounce (200ms) + network + render
  57  |   await page.waitForTimeout(400);
  58  |   // Assert result rows appear in the results pane
  59  |   const rows = page.locator('[data-testid="result-row"]');
  60  |   await expect(rows).toHaveCount(3);
  61  |   // Also assert the input retained the value
  62  |   await expect(page.locator('input[type="search"]')).toHaveValue('吃');
  63  | });
  64  | 
  65  | // ─── AC24: kind-toggles + unit-type filters ───────────────────────────────────
  66  | 
  67  | test('AC24 — kind-toggles and unit-type filters are visible and clickable after search', async ({ page }) => {
  68  |   await page.route(SEARCH_ROUTE, (route) =>
  69  |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ query: '吃', results: FAKE_RESULTS }) })
  70  |   );
  71  |   await page.goto('/');
  72  |   await page.waitForLoadState('networkidle');
  73  |   await typeSearch(page, '吃');
  74  |   // Wait for debounce + results
  75  |   await page.waitForTimeout(400);
  76  |   await expect(page.locator('[data-testid="control-bar"]')).toBeVisible();
  77  |   // All four kind-toggle buttons should be present
  78  |   const kindButtons = page.locator('[data-testid="kind-toggles"] button');
  79  |   await expect(kindButtons).toHaveCount(4);
  80  |   // All three unit-type filter buttons should be present
  81  |   const typeButtons = page.locator('[data-testid="type-filters"] button');
  82  |   await expect(typeButtons).toHaveCount(3);
  83  | });
  84  | 
  85  | test('AC24 — clicking a kind-toggle updates result pane without page reload', async ({ page }) => {
  86  |   // First call returns all results, second call (after toggle) returns only lexical
  87  |   let callCount = 0;
  88  |   await page.route(SEARCH_ROUTE, (route) => {
  89  |     callCount++;
  90  |     const results = callCount === 1 ? FAKE_RESULTS : [FAKE_RESULTS[0]];
  91  |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ query: '吃', results }) });
  92  |   });
  93  |   await page.goto('/');
  94  |   await page.waitForLoadState('networkidle');
  95  |   const urlBefore = page.url();
  96  |   await typeSearch(page, '吃');
  97  |   await page.waitForTimeout(400);
  98  |   // Click the lexical toggle to turn it off/on
  99  |   const lexicalBtn = page.locator('[data-testid="kind-toggles"] button[data-kind="lexical"]');
  100 |   await lexicalBtn.click();
  101 |   await page.waitForTimeout(400);
  102 |   // URL must not change (no navigation)
  103 |   expect(page.url()).toBe(urlBefore);
  104 |   // New mocked search should have fired (callCount > 1)
> 105 |   expect(callCount).toBeGreaterThan(1);
      |                     ^ Error: expect(received).toBeGreaterThan(expected)
  106 | });
  107 | 
  108 | test('AC24 — clicking a unit-type filter updates result pane without page reload', async ({ page }) => {
  109 |   let callCount = 0;
  110 |   await page.route(SEARCH_ROUTE, (route) => {
  111 |     callCount++;
  112 |     const results = callCount === 1 ? FAKE_RESULTS : [FAKE_RESULTS[2]];
  113 |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ query: '吃', results }) });
  114 |   });
  115 |   await page.goto('/');
  116 |   await page.waitForLoadState('networkidle');
  117 |   const urlBefore = page.url();
  118 |   await typeSearch(page, '吃');
  119 |   await page.waitForTimeout(400);
  120 |   // Click the 'sent' (sentence) filter to toggle it
  121 |   const sentBtn = page.locator('[data-testid="type-filters"] button[data-type="sentence"]');
  122 |   await sentBtn.click();
  123 |   await page.waitForTimeout(400);
  124 |   // URL must not change (no navigation)
  125 |   expect(page.url()).toBe(urlBefore);
  126 |   // New mocked search should have fired
  127 |   expect(callCount).toBeGreaterThan(1);
  128 | });
  129 | 
```