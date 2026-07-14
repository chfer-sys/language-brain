import { test, expect, type Page } from '@playwright/test';

/**
 * Regression test: each_key_duplicate bug (Svelte 5) in HanziWithPinyin.
 *
 * Root cause: HanziWithPinyin used `{#each entries as entry (entry.char)}` as
 * its keyed each block.  When the input text contains the same character twice
 * (e.g. "昨晚" — or results whose pinyin annotation contains repeated chars),
 * two entries share the same `entry.char` key, causing Svelte 5 to throw
 * `each_key_duplicate` mid-render.  The render pass aborts, corrupting the
 * parent page's reactive state (loading=true never resets), and the user sees
 * "Searching…" forever.
 *
 * Fix: switch to index-based keying `{#each entries as entry, i (i)}`.
 * The ponytail comment in HanziWithPinyin.svelte explains the trade-off.
 *
 * This test drives the live server at http://192.168.100.101:8000/ and
 * verifies that queries with duplicate-character results resolve without
 * the each_key_duplicate error and without getting stuck in "Searching…".
 *
 * NOTE: This test is expected to FAIL on the live bundle BEFORE the fix is
 * deployed (the page hangs on "Searching…" with each_key_duplicate in console).
 * It passes after the fix is deployed.
 */

// Queries known to surface the duplicate-char bug in the live dataset.
const DUPLICATE_CHAR_QUERIES = ['昨晚', '痒痒痒', '看看'];

test.describe('HanziWithPinyin — repeated-character regression', () => {
  // Collect each_key_duplicate errors across the whole test.
  let pageErrors: string[] = [];
  test.beforeEach(async ({ page }) => {
    pageErrors = [];
    page.on('pageerror', (err) => {
      pageErrors.push(err.message);
    });
  });

  for (const query of DUPLICATE_CHAR_QUERIES) {
    test(`query "${query}" does not trigger each_key_duplicate and resolves`, async ({ page }) => {
      await page.goto('http://192.168.100.101:8000/');
      await page.waitForLoadState('networkidle');

      const input = page.locator('input[type="search"]');
      await input.click();
      await page.keyboard.type(query, { delay: 150 });

      // Wait up to 20 s for the status to leave "Searching…"
      // We check every 500 ms and fail if still searching after 5 s.
      let elapsed = 0;
      let resolved = false;
      while (elapsed < 20_000) {
        const status = page.locator('.status');
        const statusText = await status.textContent().catch(() => '');
        if (statusText !== 'Searching…') {
          resolved = true;
          break;
        }
        await page.waitForTimeout(500);
        elapsed += 500;
      }

      // Assert: no each_key_duplicate pageerror
      const dupErrors = pageErrors.filter((e) => e.includes('each_key_duplicate'));
      expect(dupErrors, `each_key_duplicate errors: ${JSON.stringify(dupErrors)}`).toHaveLength(0);

      // Assert: page resolved (did not stay stuck on "Searching…")
      expect(resolved, `page stayed stuck on "Searching…" for ${elapsed}ms`).toBe(true);
    });
  }
});
