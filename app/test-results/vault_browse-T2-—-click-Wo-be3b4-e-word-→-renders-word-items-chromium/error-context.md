# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: vault_browse.spec.ts >> T2 — click Word tab → mock sees type=word → renders word items
- Location: tests/vault_browse.spec.ts:68:1

# Error details

```
Error: expect(received).toBe(expected) // Object.is equality

Expected: "word"
Received: null
```

# Page snapshot

```yaml
- generic [ref=e2]:
  - main [ref=e3]:
    - generic [ref=e4]:
      - link "← Back" [ref=e5] [cursor=pointer]:
        - /url: /
      - heading "Browse vault" [level=1] [ref=e6]
    - generic [ref=e7]:
      - tablist "Unit type" [ref=e8]:
        - tab "Word" [selected] [ref=e9] [cursor=pointer]
        - tab "Compound" [ref=e10] [cursor=pointer]
        - tab "Sentence" [ref=e11] [cursor=pointer]
      - generic [ref=e12]:
        - text: sort
        - combobox "Sort order" [ref=e13] [cursor=pointer]:
          - option "id" [selected]
          - option "pinyin"
    - paragraph [ref=e14]: Loading…
  - generic [ref=e15]: Browse vault · Language Brain
```

# Test source

```ts
  1   | import { test, expect, type Page } from '@playwright/test';
  2   | 
  3   | // ─── Shared helpers ─────────────────────────────────────────────────────────
  4   | 
  5   | const VAULT_ROUTE = /http:\/\/localhost:8000\/api\/vault\/list/;
  6   | 
  7   | const FAKE_SENTENCE_ITEMS = [
  8   |   { id: 'S1', name: '我流口水了', snippet: 'wǒ liú kǒu shuǐ le' },
  9   |   { id: 'S2', name: '今天天气很好', snippet: 'jīntiān tiānqì hěn hǎo' }
  10  | ];
  11  | 
  12  | const FAKE_WORD_ITEMS = [
  13  |   { id: 'W1', name: '吃', snippet: 'chī' },
  14  |   { id: 'W2', name: '喝', snippet: 'hē' }
  15  | ];
  16  | 
  17  | const FAKE_COMPOUND_ITEMS = [
  18  |   { id: 'C1', name: '吃饭', snippet: 'chīfàn' },
  19  |   { id: 'C2', name: '喝水', snippet: 'hēshuǐ' }
  20  | ];
  21  | 
  22  | function makeVaultResponse(
  23  |   type: string,
  24  |   items: unknown[],
  25  |   total?: number,
  26  |   sort = 'id'
  27  | ) {
  28  |   return {
  29  |     type,
  30  |     total: total ?? items.length,
  31  |     limit: 50,
  32  |     offset: 0,
  33  |     sort,
  34  |     items
  35  |   };
  36  | }
  37  | 
  38  | function setupVaultRoute(page: Page, response: unknown) {
  39  |   page.route(VAULT_ROUTE, (route) =>
  40  |     route.fulfill({
  41  |       status: 200,
  42  |       contentType: 'application/json',
  43  |       body: JSON.stringify(response)
  44  |     })
  45  |   );
  46  | }
  47  | 
  48  | // ─── Test 1: Sentence tab active by default, list renders ──────────────────
  49  | 
  50  | test('T1 — navigate to /vault → Sentence tab active → list renders rows', async ({ page }) => {
  51  |   setupVaultRoute(page, makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS));
  52  |   await page.goto('/vault');
  53  |   await page.waitForLoadState('networkidle');
  54  | 
  55  |   // Sentence tab is active.
  56  |   const sentTab = page.locator('[role="tab"][data-type="sentence"]');
  57  |   await expect(sentTab).toHaveAttribute('aria-selected', 'true');
  58  | 
  59  |   // List renders rows.
  60  |   const rows = page.locator('[data-testid="vault-list"] .row');
  61  |   await expect(rows).toHaveCount(2);
  62  |   await expect(rows.nth(0)).toContainText('S1');
  63  |   await expect(rows.nth(0)).toContainText('我流口水了');
  64  | });
  65  | 
  66  | // ─── Test 2: Word tab ───────────────────────────────────────────────────────
  67  | 
  68  | test('T2 — click Word tab → mock sees type=word → renders word items', async ({ page }) => {
  69  |   let capturedType: string | null = null;
  70  |   page.route(VAULT_ROUTE, (route) => {
  71  |     const url = new URL(route.request().url());
  72  |     capturedType = url.searchParams.get('type');
  73  |     if (capturedType === 'word') {
  74  |       route.fulfill({
  75  |         status: 200,
  76  |         contentType: 'application/json',
  77  |         body: JSON.stringify(makeVaultResponse('word', FAKE_WORD_ITEMS))
  78  |       });
  79  |     } else {
  80  |       route.fulfill({
  81  |         status: 200,
  82  |         contentType: 'application/json',
  83  |         body: JSON.stringify(makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS))
  84  |       });
  85  |     }
  86  |   });
  87  | 
  88  |   await page.goto('/vault');
  89  |   await page.waitForLoadState('networkidle');
  90  | 
  91  |   // Click word tab.
  92  |   await page.locator('[role="tab"][data-type="word"]').click();
  93  |   await page.waitForLoadState('networkidle');
  94  | 
> 95  |   expect(capturedType).toBe('word');
      |                        ^ Error: expect(received).toBe(expected) // Object.is equality
  96  |   const rows = page.locator('[data-testid="vault-list"] .row');
  97  |   await expect(rows).toHaveCount(2);
  98  |   await expect(rows.nth(0)).toContainText('W1');
  99  | });
  100 | 
  101 | // ─── Test 3: Compound tab ────────────────────────────────────────────────────
  102 | 
  103 | test('T3 — click Compound tab → renders compound items', async ({ page }) => {
  104 |   let capturedType: string | null = null;
  105 |   page.route(VAULT_ROUTE, (route) => {
  106 |     const url = new URL(route.request().url());
  107 |     capturedType = url.searchParams.get('type');
  108 |     if (capturedType === 'compound') {
  109 |       route.fulfill({
  110 |         status: 200,
  111 |         contentType: 'application/json',
  112 |         body: JSON.stringify(makeVaultResponse('compound', FAKE_COMPOUND_ITEMS))
  113 |       });
  114 |     } else {
  115 |       route.fulfill({
  116 |         status: 200,
  117 |         contentType: 'application/json',
  118 |         body: JSON.stringify(makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS))
  119 |       });
  120 |     }
  121 |   });
  122 | 
  123 |   await page.goto('/vault');
  124 |   await page.waitForLoadState('networkidle');
  125 | 
  126 |   await page.locator('[role="tab"][data-type="compound"]').click();
  127 |   await page.waitForLoadState('networkidle');
  128 | 
  129 |   expect(capturedType).toBe('compound');
  130 |   const rows = page.locator('[data-testid="vault-list"] .row');
  131 |   await expect(rows).toHaveCount(2);
  132 |   await expect(rows.nth(0)).toContainText('C1');
  133 | });
  134 | 
  135 | // ─── Test 4: Sort by pinyin ──────────────────────────────────────────────────
  136 | 
  137 | test('T4 — change sort to pinyin → second request has sort=pinyin', async ({ page }) => {
  138 |   let capturedSort: string | null = null;
  139 |   page.route(VAULT_ROUTE, (route) => {
  140 |     const url = new URL(route.request().url());
  141 |     capturedSort = url.searchParams.get('sort');
  142 |     route.fulfill({
  143 |       status: 200,
  144 |       contentType: 'application/json',
  145 |       body: JSON.stringify(makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS, 2, capturedSort ?? 'id'))
  146 |     });
  147 |   });
  148 | 
  149 |   await page.goto('/vault');
  150 |   await page.waitForLoadState('networkidle');
  151 |   // First call — default sort=id.
  152 |   expect(capturedSort).toBe('id');
  153 | 
  154 |   // Change sort to pinyin.
  155 |   await page.locator('.sort-select').selectOption('pinyin');
  156 |   await page.waitForLoadState('networkidle');
  157 |   expect(capturedSort).toBe('pinyin');
  158 | });
  159 | 
  160 | // ─── Test 5: Click row navigates to /unit/{id} ───────────────────────────────
  161 | 
  162 | test('T5 — click a row → navigates to /unit/{id}', async ({ page }) => {
  163 |   setupVaultRoute(page, makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS));
  164 |   await page.goto('/vault');
  165 |   await page.waitForLoadState('networkidle');
  166 | 
  167 |   await page.locator('[data-testid="vault-list"] .row').first().click();
  168 |   await expect(page).toHaveURL(/\/unit\/S1/);
  169 | });
  170 | 
  171 | // ─── Test 6: Pagination prev/next visibility ────────────────────────────────
  172 | 
  173 | test('T6 — prev/next visible when total > 50, hidden when total <= 50', async ({ page }) => {
  174 |   // total > 50 → pagination visible.
  175 |   setupVaultRoute(page, makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS, 100));
  176 |   await page.goto('/vault');
  177 |   await page.waitForLoadState('networkidle');
  178 |   await expect(page.locator('[data-testid="pagination"]')).toBeVisible();
  179 | 
  180 |   // Simulate prev/next click updates offset.
  181 |   let capturedOffset: number | null = null;
  182 |   page.route(VAULT_ROUTE, (route) => {
  183 |     const url = new URL(route.request().url());
  184 |     capturedOffset = Number(url.searchParams.get('offset') ?? 0);
  185 |     route.fulfill({
  186 |       status: 200,
  187 |       contentType: 'application/json',
  188 |       body: JSON.stringify(makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS, 100))
  189 |     });
  190 |   });
  191 | 
  192 |   await page.locator('[data-testid="pagination"] button:last-child').click(); // Next
  193 |   await page.waitForLoadState('networkidle');
  194 |   expect(capturedOffset).toBe(50);
  195 | 
```