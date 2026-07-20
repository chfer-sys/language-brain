# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: default-page.spec.ts >> AC24 — kind-toggles and unit-type filters are visible and clickable after search
- Location: tests/default-page.spec.ts:67:1

# Error details

```
Error: expect(locator).toHaveCount(expected) failed

Locator:  locator('[data-testid="type-filters"] button')
Expected: 3
Received: 4
Timeout:  5000ms

Call log:
  - Expect "toHaveCount" with timeout 5000ms
  - waiting for locator('[data-testid="type-filters"] button')
    14 × locator resolved to 4 elements
       - unexpected value "4"

```

# Page snapshot

```yaml
- generic [ref=e1]:
  - generic [ref=e2]:
    - generic [ref=e3]:
      - banner [ref=e4]:
        - heading "Language Brain" [level=1] [ref=e5]
        - paragraph [ref=e6]: 语言大脑
      - 'searchbox "Try: 看起来好吃 or 吃 or basic-verbs" [active] [ref=e8]': 吃
      - navigation "Primary" [ref=e9]:
        - link "Browse vault" [ref=e10] [cursor=pointer]:
          - /url: /vault
        - link "+ Add sentence" [ref=e11] [cursor=pointer]:
          - /url: /add
    - generic [ref=e12]:
      - group "Connection-kind filters" [ref=e13]:
        - generic [ref=e14]: kind
        - button "lex" [pressed] [ref=e15] [cursor=pointer]
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
      - list [ref=e26]:
        - listitem [ref=e27]:
          - link "吃 chī lex relevance score" [ref=e28] [cursor=pointer]:
            - /url: /unit/W174
            - generic "chī" [ref=e31]: 吃
            - generic [ref=e32]: chī
            - generic [ref=e34]: lex
            - generic "relevance score" [ref=e35]: "1.00"
          - paragraph [ref=e36]: e.g. 我喜欢吃
        - listitem [ref=e37]:
          - link "吃 饭 chī fàn lex relevance score" [ref=e38] [cursor=pointer]:
            - /url: /unit/C810
            - generic [ref=e40]:
              - generic "chī" [ref=e41]: 吃
              - generic "fàn" [ref=e42]: 饭
            - generic [ref=e43]: chī fàn
            - generic [ref=e45]: lex
            - generic "relevance score" [ref=e46]: "0.50"
          - paragraph [ref=e47]: e.g. 我吃饭
        - listitem [ref=e48]:
          - link "我 吃 饭 wǒ chī fàn lex relevance score" [ref=e49] [cursor=pointer]:
            - /url: /unit/S6
            - generic [ref=e51]:
              - generic "wǒ" [ref=e52]: 我
              - generic "chī" [ref=e53]: 吃
              - generic "fàn" [ref=e54]: 饭
            - generic [ref=e55]: wǒ chī fàn
            - generic [ref=e57]: lex
            - generic "relevance score" [ref=e58]: "0.33"
        - listitem [ref=e59]:
          - link "我 想 吃 wǒ xiǎng chī lex relevance score" [ref=e60] [cursor=pointer]:
            - /url: /unit/S9
            - generic [ref=e62]:
              - generic "wǒ" [ref=e63]: 我
              - generic "xiǎng" [ref=e64]: 想
              - generic "chī" [ref=e65]: 吃
            - generic [ref=e66]: wǒ xiǎng chī
            - generic [ref=e68]: lex
            - generic "relevance score" [ref=e69]: "0.33"
        - listitem [ref=e70]:
          - link "我 喜 欢 吃 wǒ xǐ huān chī lex relevance score" [ref=e71] [cursor=pointer]:
            - /url: /unit/S12
            - generic [ref=e73]:
              - generic "wǒ" [ref=e74]: 我
              - generic "xǐ" [ref=e75]: 喜
              - generic "huān" [ref=e76]: 欢
              - generic "chī" [ref=e77]: 吃
            - generic [ref=e78]: wǒ xǐ huān chī
            - generic [ref=e80]: lex
            - generic "relevance score" [ref=e81]: "0.25"
        - listitem [ref=e82]:
          - link "我 喜 欢 吃 wǒ xǐ huān chī lex relevance score" [ref=e83] [cursor=pointer]:
            - /url: /unit/S5
            - generic [ref=e85]:
              - generic "wǒ" [ref=e86]: 我
              - generic "xǐ" [ref=e87]: 喜
              - generic "huān" [ref=e88]: 欢
              - generic "chī" [ref=e89]: 吃
            - generic [ref=e90]: wǒ xǐ huān chī
            - generic [ref=e92]: lex
            - generic "relevance score" [ref=e93]: "0.25"
        - listitem [ref=e94]:
          - link "两 个 人 为 了 吃 不 惧 台 风 liǎng gè rén wèi le chī bù jù tái fēng lex relevance score" [ref=e95] [cursor=pointer]:
            - /url: /unit/S37
            - generic [ref=e97]:
              - generic "liǎng" [ref=e98]: 两
              - generic "gè" [ref=e99]: 个
              - generic "rén" [ref=e100]: 人
              - generic "wèi" [ref=e101]: 为
              - generic "le" [ref=e102]: 了
              - generic "chī" [ref=e103]: 吃
              - generic "bù" [ref=e104]: 不
              - generic "jù" [ref=e105]: 惧
              - generic "tái" [ref=e106]: 台
              - generic "fēng" [ref=e107]: 风
            - generic [ref=e108]: liǎng gè rén wèi le chī bù jù tái fēng
            - generic [ref=e110]: lex
            - generic "relevance score" [ref=e111]: "0.10"
        - listitem [ref=e112]:
          - link "你 想 吃 广 东 本 地 特 色 美 食 吗 nǐ xiǎng chī Guǎngdōng běndì tèsè měishí ma lex relevance score" [ref=e113] [cursor=pointer]:
            - /url: /unit/S23
            - generic [ref=e115]:
              - generic "nǐ" [ref=e116]: 你
              - generic "xiǎng" [ref=e117]: 想
              - generic "chī" [ref=e118]: 吃
              - generic "guǎng" [ref=e119]: 广
              - generic "dōng" [ref=e120]: 东
              - generic "běn" [ref=e121]: 本
              - generic "dì" [ref=e122]: 地
              - generic "tè" [ref=e123]: 特
              - generic "sè" [ref=e124]: 色
              - generic "měi" [ref=e125]: 美
              - generic "shí" [ref=e126]: 食
              - generic "ma" [ref=e127]: 吗
            - generic [ref=e128]: nǐ xiǎng chī Guǎngdōng běndì tèsè měishí ma
            - generic [ref=e130]: lex
            - generic "relevance score" [ref=e131]: "0.08"
  - generic [ref=e135]:
    - generic [ref=e136]: "[plugin:vite-plugin-svelte] src/routes/unit/[id]/+page.svelte:218:43 Can only bind to state or props https://svelte.dev/e/bind_invalid_value"
    - generic [ref=e137]: src/routes/unit/[id]/+page.svelte:218:43
    - generic [ref=e138]: "216 | <label class=\"field\"> 217 | <span class=\"label\">Pinyin</span> 218 | <input type=\"text\" bind:value={editPinyin} data-testid=\"edit-pinyin\" /> ^ 219 | </label> 220 | <label class=\"field\">"
    - generic [ref=e139]:
      - text: Click outside, press Esc key, or fix the code to dismiss.
      - text: You can also disable this overlay by setting
      - code [ref=e140]: server.hmr.overlay
      - text: to
      - code [ref=e141]: "false"
      - text: in
      - code [ref=e142]: vite.config.ts
      - text: .
```

# Test source

```ts
  1   | import { test, expect, type Page } from '@playwright/test';
  2   | 
  3   | // ─── Shared fixtures & helpers ───────────────────────────────────────────────
  4   | 
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
> 82  |   await expect(typeButtons).toHaveCount(3);
      |                             ^ Error: expect(locator).toHaveCount(expected) failed
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
  105 |   expect(callCount).toBeGreaterThan(1);
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