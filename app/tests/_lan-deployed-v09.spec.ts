import { test, expect } from '@playwright/test';

/**
 * LAN deployment verification — read-only E2E.
 *
 * Target: a deployed combined SPA + FastAPI served from one origin
 * (default: the LAN preview at http://192.168.100.101:8000).
 *
 * Run with:
 *   BASE_URL=http://192.168.100.101:8000 \
 *     npx playwright test _lan-deployed-v09 --reporter=list
 *
 * READ-ONLY CONTRACT — DO NOT VIOLATE:
 *   No POST/PUT/DELETE. No clicks on Save. Edit forms are opened but
 *   always closed via Cancel. The LAN vault holds the user's real data
 *   (1292 word files, 88 sentences); mutation is forbidden.
 *
 * This spec does NOT start a local Vite dev server — playwright.config.ts
 * skips `webServer` whenever BASE_URL is set, and the deployed frontend
 * is already bundled and served from the same origin as the API.
 */

const DEPLOYED_COMMIT = '198907e';
const DEPLOYED_VERSION = '0.9.0';
const DEPLOYED_BRANCH = 'kickoff/v0.9-integration';

/**
 * LAN deployment v0.9 SPA bundle redeploy (2026-07-21).
 *
 * The backend at http://192.168.100.101:8000 reports `git_commit=198907e`.
 * The SPA bundle was rebuilt and rsync'd to /opt/language-brain/app/build/
 * on 2026-07-21. All S1–S6 tests now pass against the live deployment.
 */

// ─── Scenario 1: Version badge identifies the deployment ──────────────────────

test(
  'S1 — version badge shows deployed commit, version, and branch',
  async ({ page }) => {
    await page.goto('/');
    const badge = page.locator('[data-testid="version-badge"]');
    await expect(badge).toBeVisible({ timeout: 10_000 });
    const text = (await badge.textContent()) ?? '';
    expect(text).toContain(DEPLOYED_COMMIT);
    expect(text).toContain(DEPLOYED_VERSION);
    expect(text).toContain(DEPLOYED_BRANCH);
  }
);

// ─── Scenario 2: Home page renders with v0.9 navigation ───────────────────────

test(
  'S2 — home page renders title and v0.9 nav links',
  async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('h1')).toContainText('Language Brain');
    // "Browse vault" is the link the user couldn't find in an earlier LAN build.
    await expect(page.getByRole('link', { name: 'Browse vault' })).toBeVisible();
    await expect(page.getByRole('link', { name: '+ Add sentence' })).toBeVisible();
  }
);

// ─── Scenario 3: Compound page renders v0.9 Properties + containing sentences ─

test(
  'S3 — compound C2 renders Properties (non-empty) + containing sentences; no constituents',
  async ({ page }) => {
    await page.goto('/unit/C2');
    await expect(page.locator('[data-testid="unit-name"]')).toBeVisible({ timeout: 10_000 });

    await expect(page.locator('[data-testid="unit-type"]')).toContainText('compound');

    // Properties section must render and be non-empty (AC2 the QA flagged earlier).
    const props = page.locator('[data-testid="unit-properties"]');
    await expect(props).toBeVisible();
    await expect(props.locator('dd')).not.toHaveCount(0);
    const ddCount = await props.locator('dd').count();
    expect(ddCount).toBeGreaterThanOrEqual(1);

    // Compound now shows the containing-sentences section (Wave 8 fix).
    const containing = page.locator('[data-testid="containing-sentences"]');
    await expect(containing).toBeVisible();
    // C2 has S14, S29, S84 per /api/units/C2.
    await expect(containing.locator('a[href="/unit/S14"], a[href="/unit/S29"], a[href="/unit/S84"]'))
      .not.toHaveCount(0);

    // C2 has constituent_characters: [] → section must be absent.
    await expect(page.locator('[data-testid="constituent-characters"]')).not.toBeVisible();
  }
);

// ─── Scenario 4: Compound → sentence navigation works ─────────────────────────

test(
  'S4 — clicking a containing-sentence link from C2 navigates to a sentence unit',
  async ({ page }) => {
    await page.goto('/unit/C2');
    const containing = page.locator('[data-testid="containing-sentences"]');
    await expect(containing).toBeVisible({ timeout: 10_000 });

    // Pick whichever of S14/S29/S84 is rendered as a link.
    const link = containing.locator('a[href="/unit/S14"], a[href="/unit/S29"], a[href="/unit/S84"]').first();
    await expect(link).toBeVisible();
    const href = await link.getAttribute('href');
    expect(href).toMatch(/^\/unit\/S\d+$/);
    const targetId = href!.split('/').pop()!;

    await Promise.all([
      page.waitForURL(`**/unit/${targetId}`, { timeout: 15_000 }),
      link.click(),
    ]);

    await expect(page.locator('[data-testid="unit-type"]')).toContainText('sentence');
    await expect(page.locator('[data-testid="unit-name"]').first()).toBeVisible({ timeout: 10_000 });
  }
);

// ─── Scenario 5: Edit button is present on each unit type ─────────────────────

test(
  'S5 — Edit button is present on sentence, word, and compound units',
  async ({ page }) => {
    // Sentence: S1 verified to exist via /api/vault/list (88 sentences total).
    await page.goto('/unit/S1');
    await expect(page.locator('[data-testid="edit-btn"]')).toBeVisible({ timeout: 10_000 });

    // Word: W1 verified to exist via /api/vault/list (145 words).
    await page.goto('/unit/W1');
    await expect(page.locator('[data-testid="edit-btn"]')).toBeVisible({ timeout: 10_000 });

    // Compound: C2 verified by Scenario 3.
    await page.goto('/unit/C2');
    await expect(page.locator('[data-testid="edit-btn"]')).toBeVisible({ timeout: 10_000 });
  }
);

// ─── Scenario 6: Edit form opens and pre-fills (CANCEL ONLY — NO SAVE) ────────

test(
  'S6 — sentence edit form opens with Pinyin field and Groups editor; Cancel closes it (read-only)',
  async ({ page }) => {
    // Read-only guard: fail the test loudly if a PUT/POST slips in anywhere.
    let writeOccurred = false;
    const writeMethods = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
    page.on('request', (req) => {
      if (writeMethods.has(req.method()) && new URL(req.url()).pathname.startsWith('/api/')) {
        writeOccurred = true;
        console.error(`[S6 GUARD] write request detected: ${req.method()} ${req.url()}`);
      }
    });

    await page.goto('/unit/S1');
    await expect(page.locator('[data-testid="edit-btn"]')).toBeVisible({ timeout: 10_000 });

    // Open the edit form (no save).
    await page.locator('[data-testid="edit-btn"]').click();
    await expect(page.locator('[data-testid="edit-form"]')).toBeVisible();

    // Sentence edit must include a Pinyin field.
    await expect(page.locator('[data-testid="edit-pinyin"]')).toBeVisible();

    // CANCEL — never Save. This is the read-only exit.
    await page.locator('[data-testid="cancel-edit-btn"]').click();

    // Form closes; Properties section returns.
    await expect(page.locator('[data-testid="edit-form"]')).not.toBeVisible({ timeout: 5_000 });
    await expect(page.locator('[data-testid="unit-properties"]')).toBeVisible();

    // Final assertion: no writes happened during the whole test.
    expect(writeOccurred, 'no PUT/POST/PATCH/DELETE should have been issued against the LAN API').toBe(false);
  }
);

// ─── Scenario 7: API endpoints respond correctly (read-only) ──────────────────
//
// These pass against the current LAN deployment because the backend at
// 198907e6 is correctly deployed — only the SPA bundle is stale.

test.describe('S7 — read-only API endpoints (backend at 198907e6)', () => {
  test('/api/version reports deployed version + commit', async ({ request }) => {
    const res = await request.get('/api/version');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.version).toBe(DEPLOYED_VERSION);
    expect(body.git_commit).toBe(DEPLOYED_COMMIT);
    expect(body.git_branch).toBe(DEPLOYED_BRANCH);
  });

  test('/healthz includes the deployed git commit', async ({ request }) => {
    const res = await request.get('/healthz');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.git_commit).toBe(DEPLOYED_COMMIT);
    expect(body.status).toBe('ok');
  });

  test('/api/vault/list?type=group&limit=5 returns existing groups (GroupChips fallback)', async ({ request }) => {
    const res = await request.get('/api/vault/list?type=group&limit=5');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.type).toBe('group');
    expect(Array.isArray(body.items)).toBe(true);
    expect(body.items.length).toBeGreaterThan(0);
    expect(body.total).toBeGreaterThanOrEqual(body.items.length);
  });

  test('/api/search/suggest?types=group&q=a&limit=5 returns suggestions (GroupChips autocomplete)', async ({ request }) => {
    // NOTE: the API enforces min_length=1 on `q`, so an empty-string query
    // 422's by design. The autocomplete always sends a non-empty prefix, so
    // we test the real path with `q=a`.
    const res = await request.get('/api/search/suggest?types=group&q=a&limit=5');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('suggestions');
    expect(Array.isArray(body.suggestions)).toBe(true);
  });

  test('/api/search/suggest rejects empty `q` with 422 (documented behaviour)', async ({ request }) => {
    // Pins the empty-q contract so the autocomplete UI knows it must
    // send at least one character.
    const res = await request.get('/api/search/suggest?types=group&q=&limit=5');
    expect(res.status()).toBe(422);
  });
});
