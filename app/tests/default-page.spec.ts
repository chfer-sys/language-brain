import { test, expect, type Page } from '@playwright/test';

// ─── Shared fixtures & helpers ───────────────────────────────────────────────

const FAKE_RESULTS = [
  { id: 'chī', type: 'word', name: '吃', snippet: 'chī', kinds: ['lexical'], score: 1.0 },
  { id: 'chīfàn', type: 'word', name: '吃饭', snippet: 'chīfàn', kinds: ['lexical'], score: 0.5 },
  { id: 's-1', type: 'sentence', name: '我喜欢吃', snippet: 'wǒ xǐhuān chī', kinds: ['lexical'], score: 0.25 }
];

// Route pattern matches the absolute API URL (app calls http://localhost:8000/api/search,
// not the same-origin /api/search path). Uses absolute URL regex like other passing tests.
const SEARCH_ROUTE = /http:\/\/localhost:8000\/api\/search/;

async function typeSearch(page: Page, text: string) {
  const input = page.locator('input[type="search"]');
  await input.click();
  await page.waitForTimeout(100);
  await page.keyboard.type(text);
  await page.waitForTimeout(50); // let event propagate
}

// ─── AC22: default page renders a search box ──────────────────────────────────

test('AC22 — renders a search input as the primary above-the-fold control', async ({ page }) => {
  await page.route(SEARCH_ROUTE, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ query: '', results: [] }) })
  );
  await page.goto('/');
  await expect(page.locator('input[type="search"]')).toBeVisible();
});

// ─── AC23: search debounce 200ms ─────────────────────────────────────────────

test('AC23 — does not call search immediately on keystroke', async ({ page }) => {
  let searchHit = false;
  page.on('request', (req) => { if (req.url().includes('/api/search')) searchHit = true; });
  await page.route(SEARCH_ROUTE, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ query: '', results: FAKE_RESULTS }) })
  );
  await page.goto('/');
  await typeSearch(page, '吃');
  await page.waitForTimeout(50);
  expect(searchHit).toBe(false);
});

// AC23: Debounce verification — verify results appear after typing stops.
// The exact timing (200ms debounce) requires fake timers which E2E doesn't support.
test('AC23 — results appear after debounce delay', async ({ page }) => {
  await page.route(SEARCH_ROUTE, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ query: '吃', results: FAKE_RESULTS }) })
  );
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  await typeSearch(page, '吃');
  // Wait for debounce (200ms) + network + render
  await page.waitForTimeout(400);
  // Assert result rows appear in the results pane
  const rows = page.locator('[data-testid="result-row"]');
  await expect(rows).toHaveCount(3);
  // Also assert the input retained the value
  await expect(page.locator('input[type="search"]')).toHaveValue('吃');
});

// ─── AC24: kind-toggles + unit-type filters ───────────────────────────────────

test('AC24 — kind-toggles and unit-type filters are visible and clickable after search', async ({ page }) => {
  await page.route(SEARCH_ROUTE, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ query: '吃', results: FAKE_RESULTS }) })
  );
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  await typeSearch(page, '吃');
  // Wait for debounce + results
  await page.waitForTimeout(400);
  await expect(page.locator('[data-testid="control-bar"]')).toBeVisible();
  // All four kind-toggle buttons should be present
  const kindButtons = page.locator('[data-testid="kind-toggles"] button');
  await expect(kindButtons).toHaveCount(4);
  // All three unit-type filter buttons should be present
  const typeButtons = page.locator('[data-testid="type-filters"] button');
  await expect(typeButtons).toHaveCount(3);
});

test('AC24 — clicking a kind-toggle updates result pane without page reload', async ({ page }) => {
  // First call returns all results, second call (after toggle) returns only lexical
  let callCount = 0;
  await page.route(SEARCH_ROUTE, (route) => {
    callCount++;
    const results = callCount === 1 ? FAKE_RESULTS : [FAKE_RESULTS[0]];
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ query: '吃', results }) });
  });
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  const urlBefore = page.url();
  await typeSearch(page, '吃');
  await page.waitForTimeout(400);
  // Click the lexical toggle to turn it off/on
  const lexicalBtn = page.locator('[data-testid="kind-toggles"] button[data-kind="lexical"]');
  await lexicalBtn.click();
  await page.waitForTimeout(400);
  // URL must not change (no navigation)
  expect(page.url()).toBe(urlBefore);
  // New mocked search should have fired (callCount > 1)
  expect(callCount).toBeGreaterThan(1);
});

test('AC24 — clicking a unit-type filter updates result pane without page reload', async ({ page }) => {
  let callCount = 0;
  await page.route(SEARCH_ROUTE, (route) => {
    callCount++;
    const results = callCount === 1 ? FAKE_RESULTS : [FAKE_RESULTS[2]];
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ query: '吃', results }) });
  });
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  const urlBefore = page.url();
  await typeSearch(page, '吃');
  await page.waitForTimeout(400);
  // Click the 'sent' (sentence) filter to toggle it
  const sentBtn = page.locator('[data-testid="type-filters"] button[data-type="sentence"]');
  await sentBtn.click();
  await page.waitForTimeout(400);
  // URL must not change (no navigation)
  expect(page.url()).toBe(urlBefore);
  // New mocked search should have fired
  expect(callCount).toBeGreaterThan(1);
});
