// Recovery verification: confirm no stuck-Searching state after cache-control fix.
// Targets the live container at 192.168.100.101:8000.
import { test, expect } from '@playwright/test';

const REMOTE = 'http://192.168.100.101:8000';
const DURATION_MS = 25_000;
const SAMPLE_MS = 500;

test('live-recovery-verify — no stuck Searching state over 25 s', async ({ page }) => {
  const t0 = Date.now();

  // Screenshot helper
  async function screenshot(label: string) {
    await page.screenshot({
      path: `/tmp/lb-recovery-${label}-${Date.now()}.png`,
      fullPage: false
    });
  }

  await page.goto(REMOTE);

  // Verify version.json to confirm the PR#1 bundle is live.
  const verResp = await page.request.get(`${REMOTE}/_app/version.json`);
  expect(verResp.status()).toBe(200);
  const version = (await verResp.json()).version;
  console.log(`live bundle version: ${version}`);

  // Verify cache-control headers on the SPA responses.
  const rootResp = await page.request.get(`${REMOTE}/`);
  expect(rootResp.headers()['cache-control']).toContain('no-cache');
  const versionResp = await page.request.get(`${REMOTE}/_app/version.json`);
  expect(versionResp.headers()['cache-control']).toContain('no-cache');

  const input = page.locator('input[type="search"]');
  await expect(input).toBeVisible();
  console.log('search input visible');

  // Capture t=1s screenshot
  await page.waitForTimeout(1_000);
  await screenshot('1s');

  // Type the query — this triggers the debounced search.
  await input.fill('测试');
  console.log('typed "测试", starting 25 s sample loop');

  // Sample every SAMPLE_MS for DURATION_MS. The PR#1 fix sets a 15 s AbortController
  // timeout that transitions "Searching…" → error state. The bug (old stale bundle
  // with no timeout) leaves "Searching…" indefinitely. Assertion: after the first
  // "Searching…" is observed, it MUST resolve to a non-Searching state within 20 s.
  // (20 s gives 5 s margin over the 15 s hard timeout.)
  const totalSamples = Math.floor(DURATION_MS / SAMPLE_MS);
  let stuckAt: number | null = null;
  for (let i = 0; i < totalSamples; i++) {
    await page.waitForTimeout(SAMPLE_MS);
    const statusEls = page.locator('.status');
    const count = await statusEls.count();
    if (count > 0) {
      const text = (await statusEls.first().innerText()).trim();
      console.log(`t=${Date.now() - t0}ms  .status="${text}"`);
      if (text === 'Searching…') {
        if (stuckAt === null) stuckAt = Date.now() - t0;
        // FAIL if still Searching more than 20 s after it first appeared.
        expect(
          Date.now() - t0 - stuckAt,
          `Still "Searching…" ${Date.now() - t0 - stuckAt} ms after first appearance — stuck!`
        ).toBeLessThan(20_000);
      } else {
        // Resolved to something else (Results, No results, Error, filter notice).
        stuckAt = null;
      }
    }
    // Screenshots at t=1 s (done), t=10 s, t=24 s.
    if (i === Math.floor(10_000 / SAMPLE_MS) || i === Math.floor(24_000 / SAMPLE_MS)) {
      await screenshot(`${i * SAMPLE_MS / 1000}s`);
    }
  }

  // Final screenshot at end.
  await screenshot('25s-end');
  console.log('25 s sample loop complete — PASS: no stuck Searching… detected');
});
