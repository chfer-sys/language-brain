import { test, expect, type Page } from '@playwright/test';

// Matches both http://127.0.0.1:8000 and http://localhost:8000 (known mock mismatch — AGENTS.md).
const VERSION_PATTERN = /127\.0\.0\.1:8000\/api\/version|localhost:8000\/api\/version/;

function mockVersionSuccess(page: Page) {
  page.route(VERSION_PATTERN, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        version: '0.9.0',
        git_commit: 'abc1234',
        git_branch: 'kickoff/v0.9-integration',
        python_version: '3.11.0',
        timestamp: '2026-07-21T12:00:00Z'
      })
    })
  );
}

test('version badge renders with correct values from /api/version', async ({ page }) => {
  mockVersionSuccess(page);
  await page.goto('/');
  await page.waitForSelector('[data-testid="version-badge"]', { timeout: 10_000 });
  const badge = page.locator('[data-testid="version-badge"]');
  await expect(badge).toBeVisible();
  const text = await badge.textContent();
  expect(text).toContain('v0.9.0');
  expect(text).toContain('abc1234');
  expect(text).toContain('kickoff/v0.9-integration');
});

test('version badge is absent when /api/version returns an error', async ({ page }) => {
  page.route(VERSION_PATTERN, (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: '{}' })
  );
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  const badge = page.locator('[data-testid="version-badge"]');
  await expect(badge).toBeHidden();
});

test('version badge is present on /vault page', async ({ page }) => {
  mockVersionSuccess(page);
  const vaultPattern = /127\.0\.0\.1:8000\/api\/vault\/list|localhost:8000\/api\/vault\/list/;
  page.route(vaultPattern, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ type: 'sentence', total: 0, limit: 50, offset: 0, sort: 'id', items: [] })
    })
  );
  await page.goto('/vault');
  await page.waitForSelector('[data-testid="version-badge"]', { timeout: 10_000 });
  const badge = page.locator('[data-testid="version-badge"]');
  await expect(badge).toBeVisible();
});
