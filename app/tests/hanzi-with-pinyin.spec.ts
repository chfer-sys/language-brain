import { test, expect, type Page } from '@playwright/test';

// HanziWithPinyin is rendered inside ResultRow on the search results page.
// These tests verify the integration — that the default page search flow works
// and shows hanzi via HanziWithPinyin. Component-internal behavior
// (tone classes, per-char pinyin tooltips, fetch fallback) is preserved
// by the passing add-page and unit-detail tests that exercise pages
// containing HanziWithPinyin.

const FAKE_RESULTS = [
  { id: 'chi', type: 'word', name: '吃', snippet: 'chī', kinds: ['lexical'], score: 1.0 },
  { id: 's-1', type: 'sentence', name: '我喜欢吃', snippet: 'wǒ xǐhuān chī', kinds: ['lexical'], score: 0.5 }
];

// Route pattern matches the absolute API URL (same as default-page.spec.ts).
const SEARCH_ROUTE = /http:\/\/localhost:8000\/api\/search/;

test('T4 — default page search shows hanzi via HanziWithPinyin', async ({ page }) => {
  // Mock search endpoint
  await page.route(SEARCH_ROUTE, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ query: '吃', results: FAKE_RESULTS }) })
  );
  // Mock pinyin endpoint so HanziWithPinyin gets tone data
  await page.route(/http:\/\/localhost:8000\/api\/pinyin\//, (route) => {
    const url = route.request().url();
    const text = url.includes('/api/pinyin/') ? decodeURIComponent(url.split('/api/pinyin/')[1]) : '';
    // Return per-char entries with tone info
    const entries = text.split('').map((ch: string) => ({
      char: ch,
      pinyin: ch === '吃' ? 'chī' : '',
      tone: ch === '吃' ? 1 : 5
    }));
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(entries) });
  });
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  // Use click + keyboard.type for reliable Svelte input handling (same as default-page.spec.ts)
  const input = page.locator('input[type="search"]');
  await input.click();
  await page.waitForTimeout(100);
  await page.keyboard.type('吃');
  // Wait for debounce (200ms) + network + render
  await page.waitForTimeout(500);
  // Verify search input received the value
  await expect(page.locator('input[type="search"]')).toHaveValue('吃');
  // Verify result rows appear
  const rows = page.locator('[data-testid="result-row"]');
  await expect(rows).toHaveCount(2);
  // Verify HanziWithPinyin renders the hanzi character with tone-1 class
  // (the component exposes per-char spans with data-tone and data-pinyin attributes)
  // Use .first() because both "吃" (word) and "我喜欢吃" (sentence) contain "吃"
  const hanziSpan = page.locator('[data-testid="result-name-char-吃"]').first();
  await expect(hanziSpan).toBeVisible();
  await expect(hanziSpan).toHaveAttribute('data-tone', '1');
  await expect(hanziSpan).toHaveAttribute('data-pinyin', 'chī');
  // The tone-1 class applies a red underline (border-bottom-color: #dc2626)
  await expect(hanziSpan).toHaveClass(/tone-1/);
});
