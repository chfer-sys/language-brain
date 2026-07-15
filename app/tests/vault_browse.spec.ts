import { test, expect, type Page } from '@playwright/test';

// ─── Shared helpers ─────────────────────────────────────────────────────────

const VAULT_ROUTE = /http:\/\/localhost:8000\/api\/vault\/list/;

const FAKE_SENTENCE_ITEMS = [
  { id: 'S1', name: '我流口水了', snippet: 'wǒ liú kǒu shuǐ le' },
  { id: 'S2', name: '今天天气很好', snippet: 'jīntiān tiānqì hěn hǎo' }
];

const FAKE_WORD_ITEMS = [
  { id: 'W1', name: '吃', snippet: 'chī' },
  { id: 'W2', name: '喝', snippet: 'hē' }
];

const FAKE_COMPOUND_ITEMS = [
  { id: 'C1', name: '吃饭', snippet: 'chīfàn' },
  { id: 'C2', name: '喝水', snippet: 'hēshuǐ' }
];

function makeVaultResponse(
  type: string,
  items: unknown[],
  total?: number,
  sort = 'id'
) {
  return {
    type,
    total: total ?? items.length,
    limit: 50,
    offset: 0,
    sort,
    items
  };
}

function setupVaultRoute(page: Page, response: unknown) {
  page.route(VAULT_ROUTE, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(response)
    })
  );
}

// ─── Test 1: Sentence tab active by default, list renders ──────────────────

test('T1 — navigate to /vault → Sentence tab active → list renders rows', async ({ page }) => {
  setupVaultRoute(page, makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS));
  await page.goto('/vault');
  await page.waitForLoadState('networkidle');

  // Sentence tab is active.
  const sentTab = page.locator('[role="tab"][data-type="sentence"]');
  await expect(sentTab).toHaveAttribute('aria-selected', 'true');

  // List renders rows.
  const rows = page.locator('[data-testid="vault-list"] .row');
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText('S1');
  await expect(rows.nth(0)).toContainText('我流口水了');
});

// ─── Test 2: Word tab ───────────────────────────────────────────────────────

test('T2 — click Word tab → mock sees type=word → renders word items', async ({ page }) => {
  let capturedType: string | null = null;
  page.route(VAULT_ROUTE, (route) => {
    const url = new URL(route.request().url());
    capturedType = url.searchParams.get('type');
    if (capturedType === 'word') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeVaultResponse('word', FAKE_WORD_ITEMS))
      });
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS))
      });
    }
  });

  await page.goto('/vault');
  await page.waitForLoadState('networkidle');

  // Click word tab.
  await page.locator('[role="tab"][data-type="word"]').click();
  await page.waitForLoadState('networkidle');

  expect(capturedType).toBe('word');
  const rows = page.locator('[data-testid="vault-list"] .row');
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText('W1');
});

// ─── Test 3: Compound tab ────────────────────────────────────────────────────

test('T3 — click Compound tab → renders compound items', async ({ page }) => {
  let capturedType: string | null = null;
  page.route(VAULT_ROUTE, (route) => {
    const url = new URL(route.request().url());
    capturedType = url.searchParams.get('type');
    if (capturedType === 'compound') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeVaultResponse('compound', FAKE_COMPOUND_ITEMS))
      });
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS))
      });
    }
  });

  await page.goto('/vault');
  await page.waitForLoadState('networkidle');

  await page.locator('[role="tab"][data-type="compound"]').click();
  await page.waitForLoadState('networkidle');

  expect(capturedType).toBe('compound');
  const rows = page.locator('[data-testid="vault-list"] .row');
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText('C1');
});

// ─── Test 4: Sort by pinyin ──────────────────────────────────────────────────

test('T4 — change sort to pinyin → second request has sort=pinyin', async ({ page }) => {
  let capturedSort: string | null = null;
  page.route(VAULT_ROUTE, (route) => {
    const url = new URL(route.request().url());
    capturedSort = url.searchParams.get('sort');
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS, 2, capturedSort ?? 'id'))
    });
  });

  await page.goto('/vault');
  await page.waitForLoadState('networkidle');
  // First call — default sort=id.
  expect(capturedSort).toBe('id');

  // Change sort to pinyin.
  await page.locator('.sort-select').selectOption('pinyin');
  await page.waitForLoadState('networkidle');
  expect(capturedSort).toBe('pinyin');
});

// ─── Test 5: Click row navigates to /unit/{id} ───────────────────────────────

test('T5 — click a row → navigates to /unit/{id}', async ({ page }) => {
  setupVaultRoute(page, makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS));
  await page.goto('/vault');
  await page.waitForLoadState('networkidle');

  await page.locator('[data-testid="vault-list"] .row').first().click();
  await expect(page).toHaveURL(/\/unit\/S1/);
});

// ─── Test 6: Pagination prev/next visibility ────────────────────────────────

test('T6 — prev/next visible when total > 50, hidden when total <= 50', async ({ page }) => {
  // total > 50 → pagination visible.
  setupVaultRoute(page, makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS, 100));
  await page.goto('/vault');
  await page.waitForLoadState('networkidle');
  await expect(page.locator('[data-testid="pagination"]')).toBeVisible();

  // Simulate prev/next click updates offset.
  let capturedOffset: number | null = null;
  page.route(VAULT_ROUTE, (route) => {
    const url = new URL(route.request().url());
    capturedOffset = Number(url.searchParams.get('offset') ?? 0);
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS, 100))
    });
  });

  await page.locator('[data-testid="pagination"] button:last-child').click(); // Next
  await page.waitForLoadState('networkidle');
  expect(capturedOffset).toBe(50);

  // total <= 50 → pagination hidden.
  await page.goto('/vault');
  await page.waitForLoadState('networkidle');
  // Override mock for this page visit.
  page.route(VAULT_ROUTE, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS, 2))
    })
  );
  // Reload to re-trigger load().
  await page.reload();
  await page.waitForLoadState('networkidle');
  await expect(page.locator('[data-testid="pagination"]')).not.toBeVisible();
});

// ─── Test 7: Browse vault link on / navigates to /vault ─────────────────────

test('T7 — "Browse vault" link on / navigates to /vault', async ({ page }) => {
  // Mock the search endpoint so the page loads cleanly.
  page.route(/http:\/\/localhost:8000\/api\/search/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ query: '', results: [] })
    })
  );
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const link = page.locator('a.add-link[href="/vault"]', { hasText: 'Browse vault' });
  await expect(link).toBeVisible();
  await link.click();
  await expect(page).toHaveURL('/vault');
});
