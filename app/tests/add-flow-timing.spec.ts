import { test, expect } from '@playwright/test';

/**
 * Live /add flow timing spec — measures propose + commit latency.
 *
 * Target: a deployed combined SPA + FastAPI served from one origin
 * (default: the LAN preview at http://192.168.100.101:8000).
 *
 * Run with:
 *   BASE_URL=http://192.168.100.101:8000 \
 *     npx playwright test add-flow-timing --reporter=list
 *
 * This spec MUTATES the vault (creates a real sentence). It is
 * intended for post-deploy verification of the commit-path latency
 * after the embed_batch optimization. The sentence is left in the
 * vault — no DELETE endpoint exists for sentences.
 *
 * Follows the conventions of _lan-deployed-v09.spec.ts: only runs
 * when BASE_URL is set (playwright.config.ts skips webServer).
 */

test.describe('live /add flow timing', () => {
  test.skip(!process.env.BASE_URL, 'BASE_URL not set — skipping live timing spec');

  test(
    'propose + commit latency within budget after embed_batch fix',
    async ({ page, request }) => {
      // Generous timeout: AI propose is ~22s real-world; commit after
      // embed_batch fix should be ~1-2s (was 2-4s+).
      test.setTimeout(180_000);

      await page.goto('/add');
      await expect(page.locator('[data-testid="hanzi-input"]')).toBeVisible({ timeout: 10_000 });

      // Fill the form.
      await page.locator('[data-testid="hanzi-input"]').fill('她昨天买了很多水果');
      await page.locator('input[type="text"]').first().fill('She bought a lot of fruit yesterday');

      // Propose — time the AI round-trip.
      const proposeBtn = page.locator('[data-testid="propose-btn"]');
      await expect(proposeBtn).toBeEnabled();
      const t0 = Date.now();
      await proposeBtn.click();
      await expect(page.locator('[data-testid="proposed-form"]')).toBeVisible({ timeout: 60_000 });
      const proposeMs = Date.now() - t0;

      // Commit — time the save round-trip.
      const t1 = Date.now();
      await page.locator('[data-testid="save-btn"]').click();
      const saved = page.locator('[data-testid="saved"]');
      await expect(saved).toBeVisible({ timeout: 30_000 });
      const commitMs = Date.now() - t1;

      // Extract the created sentence id from the saved confirmation.
      const savedText = (await saved.textContent()) ?? '';
      const sentenceIdMatch = savedText.match(/S\d+/);
      const sentenceId = sentenceIdMatch ? sentenceIdMatch[0] : 'unknown';

      // Log timings.
      const timings = { proposeMs, commitMs, sentenceId };
      console.log('[add-flow-timing]', JSON.stringify(timings));
      await test.info().attach('timings', {
        body: JSON.stringify(timings, null, 2),
        contentType: 'application/json',
      });

      // Assertions — propose < 60s (AI can be slow), commit < 10s (embed_batch fix target).
      expect(proposeMs, `propose took ${proposeMs}ms, expected < 60000`).toBeLessThan(60_000);
      expect(commitMs, `commit took ${commitMs}ms, expected < 10000`).toBeLessThan(10_000);

      // Cleanup: no DELETE /api/sentences/{id} endpoint exists. Log and move on.
      const openapiRes = await request.get('/openapi.json');
      if (openapiRes.ok()) {
        const openapi = await openapiRes.json();
        const hasDelete = Object.keys(openapi.paths ?? {}).some((p) =>
          p.startsWith('/api/sentences/{') && openapi.paths[p].delete
        );
        if (hasDelete && sentenceId !== 'unknown') {
          const delRes = await request.delete(`/api/sentences/${sentenceId}`);
          console.log(`[add-flow-timing] cleanup: DELETE /api/sentences/${sentenceId} → ${delRes.status()}`);
        } else {
          console.log(`[add-flow-timing] cleanup: sentence ${sentenceId} remains in vault (no DELETE endpoint)`);
        }
      } else {
        console.log(`[add-flow-timing] cleanup: could not fetch openapi.json (status ${openapiRes.status()})`);
      }
    }
  );
});
