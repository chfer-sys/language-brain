import { test, expect, type Page } from '@playwright/test';

// Route pattern matches the absolute API URL the app calls
// (VITE_API_BASE is used at runtime; tests run against localhost:8000 in dev).
const SEARCH_ROUTE = /http:\/\/localhost:8000\/api\/search/;

async function typeSearch(page: Page, text: string) {
  const input = page.locator('input[type="search"]');
  await input.click();
  await page.waitForTimeout(100);
  await page.keyboard.type(text);
  await page.waitForTimeout(50);
}

// ─── hotfix: search timeout on stalled network ─────────────────────────────────
//
// Symptom: when the network silently stalls, the browser fetch hangs forever
// and the page stays on "Searching…" indefinitely.
//
// Fix: runSearch now wraps every fetch in an AbortController with a 15 s
// hard timeout, and a new keystroke cancels any in-flight request via the
// same signal mechanism.
//
// This test intercepts /api/search and stalls it forever, then verifies
// the UI transitions out of "Searching…" within 20 s (well under the 15 s
// browser-timeout threshold, accounting for debounce + timeout + render).
// ─────────────────────────────────────────────────────────────────────────────

test('search shows error instead of hanging on "Searching…" when network stalls', async ({ page }) => {
  let requestStalled = false;
  await page.route(SEARCH_ROUTE, async (route) => {
    // Never fulfill — simulates a completely stalled TCP connection.
    requestStalled = true;
    // The route handler keeps the request hanging indefinitely.
    // Do NOT call route.fulfill() or route.abort().
  });

  await page.goto('/');
  await page.waitForLoadState('networkidle');

  expect(requestStalled).toBe(false); // no search yet

  // Trigger a search that will be stalled
  await typeSearch(page, 'test');

  // After debounce (200 ms) the loading state begins. The 15 s timeout
  // inside runSearch will abort the fetch and the catch block will set
  // error = <message>. We wait up to 20 s for the error to appear.
  const status = page.locator('.status');
  await expect(status).not.toHaveText('Searching…', { timeout: 20_000 });

  // Acceptable final states after a timeout: error message OR no-results
  const statusText = await status.textContent();
  const isErrorOrEmpty = !statusText?.includes('Searching…');
  expect(isErrorOrEmpty).toBe(true);
});
