import { test, expect, type Page } from '@playwright/test';

// Target the live production server (SvelteKit static build served by FastAPI)
const BASE_URL = 'http://192.168.100.101:8000';
const SEARCH_ROUTE = /192\.168\.100\.101:8000\/api\/search/;

async function typeSearch(page: Page, text: string) {
  const input = page.locator('input[type="search"]');
  await input.click();
  await input.fill(text);
  await page.waitForTimeout(50);
}

// ─── Repro: search "昨晚" vs "吃" on live server ─────────────────────────────────
//
// Symptom reported: "吃" is fast; "昨晚" hangs on "Searching…" indefinitely.
// Backend curl probes show both queries return 200 in <200 ms.
//
// This test forces cache bypass via cache-control: no-cache so we don't
// hit any cached bundle. It verifies:
//   (a) "吃" transitions to results within 2 s
//   (b) "昨晚" does NOT stay on "Searching…" past the 15 s AbortController
//       timeout (i.e. either results, no-results, or error text appears
//       within ~17 s to account for debounce + network + timeout + render).
// ─────────────────────────────────────────────────────────────────────────────

test('live server: "吃" returns results within 2 s', async ({ page }) => {
  const requests: { url: string; status?: number; bodyLength?: number; timing: number }[] = [];
  const start = Date.now();

  await page.route(SEARCH_ROUTE, async (route) => {
    const reqUrl = route.request().url();
    const t0 = Date.now() - start;
    requests.push({ url: reqUrl, timing: t0 });

    // Force cache bypass on the request to the API
    const existing = route.request().headers();
    const headers: Record<string, string> = {
      ...existing,
      'cache-control': 'no-cache',
    };

    await route.fetch({ headers });
    const resp = await route.fetch({ headers });
    const status = resp.status();
    const body = await resp.body();
    const t1 = Date.now() - start;
    requests[requests.length - 1]!.status = status;
    requests[requests.length - 1]!.bodyLength = body.length;
    requests[requests.length - 1]!.timing = t1;

    await route.fulfill({
      status,
      contentType: 'application/json',
      body,
    });
  });

  await page.goto(BASE_URL, { headers: { 'cache-control': 'no-cache' } });
  await page.waitForLoadState('networkidle');

  // Type "吃" (control case — user says this is fast)
  await typeSearch(page, '吃');

  // Wait for results (should appear within 2 s)
  const status = page.locator('.status');
  try {
    await expect(page.locator('[data-testid="results"]')).toBeVisible({ timeout: 2_000 });
  } catch {
    // If no results, that's also OK (empty vault) — just not "Searching…"
    const text = await status.textContent();
    console.log('[repro] "吃" final status:', text);
    expect(text).not.toContain('Searching…');
  }

  console.log('[repro] "吃" requests:', JSON.stringify(requests, null, 2));
});

test('live server: "昨晚" does NOT hang past 15 s timeout', async ({ page }) => {
  const requests: { url: string; status?: number; bodyLength?: number; timing: number }[] = [];
  const start = Date.now();

  await page.route(SEARCH_ROUTE, async (route) => {
    const reqUrl = route.request().url();
    const t0 = Date.now() - start;
    requests.push({ url: reqUrl, timing: t0 });

    const headers: Record<string, string> = {
      ...route.request().headers(),
      'cache-control': 'no-cache',
    };

    await route.fetch({ headers });
    const resp = await route.fetch({ headers });
    const status = resp.status();
    const body = await resp.body();
    const t1 = Date.now() - start;
    requests[requests.length - 1]!.status = status;
    requests[requests.length - 1]!.bodyLength = body.length;
    requests[requests.length - 1]!.timing = t1;

    await route.fulfill({
      status,
      contentType: 'application/json',
      body,
    });
  });

  await page.goto(BASE_URL, { headers: { 'cache-control': 'no-cache' } });
  await page.waitForLoadState('networkidle');

  // Take screenshot at t=1 s
  await page.waitForTimeout(1_000);
  await page.screenshot({ path: '/tmp/repro-t1s.png' });

  // Type "昨晚" — the problematic query
  await typeSearch(page, '昨晚');

  // Sample .status text every 500 ms for 25 s
  const samples: { t: number; text: string }[] = [];
  const maxWait = 25_000;
  const interval = 500;
  let elapsed = 0;
  while (elapsed < maxWait) {
    const t = Date.now() - start;
    const text = await page.locator('.status').textContent().catch(() => '(unavailable)');
    samples.push({ t, text: text ?? '' });
    if (!text?.includes('Searching…')) break;
    await page.waitForTimeout(interval);
    elapsed += interval;
  }

  // Screenshot at t=5 s, 15 s, 24 s
  const t5 = Date.now() - start;
  if (t5 < 5_000) await page.waitForTimeout(5_000 - t5);
  await page.screenshot({ path: '/tmp/repro-t5s.png' });

  const t15 = Date.now() - start;
  if (t15 < 15_000) await page.waitForTimeout(15_000 - t15);
  await page.screenshot({ path: '/tmp/repro-t15s.png' });

  const t24 = Date.now() - start;
  if (t24 < 24_000) await page.waitForTimeout(24_000 - t24);
  await page.screenshot({ path: '/tmp/repro-t24s.png' });

  // Log all samples
  console.log('[repro] "昨晚" status samples:');
  for (const s of samples) {
    console.log(`  t=${s.t}ms: "${s.text}"`);
  }
  console.log('[repro] "昨晚" requests:', JSON.stringify(requests, null, 2));

  // PASS criteria: status must NOT contain "Searching…" after 17 s
  // (15 s timeout + 2 s for debounce/render)
  const lastSample = samples[samples.length - 1];
  const lastedLong = lastSample?.text?.includes('Searching…') ?? false;

  // Write trace log
  const trace = {
    query: '昨晚',
    samples,
    requests,
    lastedLong,
    pass: !lastedLong || (lastSample?.t ?? 0) < 17_000,
  };
  console.log('[repro] trace:', JSON.stringify(trace, null, 2));

  expect(lastedLong && (lastSample?.t ?? 0) >= 17_000).toBe(false);
});
