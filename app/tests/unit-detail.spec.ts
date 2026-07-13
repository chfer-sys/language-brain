import { test, expect, type Page } from '@playwright/test';

// ─── Fake payloads ───────────────────────────────────────────────────────────

const FAKE_SENTENCE = {
  id: 's-1',
  type: 'sentence',
  name: '我喜欢吃',
  properties: {
    hanzi: '我喜欢吃',
    pinyin: 'wǒ xǐhuān chī',
    english: 'I like to eat',
    meaning: 'expressing enjoyment of eating',
    words: ['我', '喜欢', '吃'],
    word_refs: ['wǒ', 'xǐhuān', 'chī'],
    groups: ['food'],
    antonyms: []
  },
  connections: [
    { to: 'chī', kind: 'lexical', score: 1.0 },
    { to: 'food', kind: 'group', score: 1.0 },
    { to: 'xǐhuān', kind: 'lexical', score: 0.67 }
  ],
  created: '2026-06-27',
  updated: '2026-06-27',
  author_confirmed: true
};

const FAKE_WORD = {
  id: 'chī',
  type: 'word',
  name: '吃',
  properties: {
    hanzi: '吃',
    pinyin: 'chī',
    english: 'to eat',
    meaning: 'the act of eating',
    groups: ['food'],
    antonyms: ['饿']
  },
  connections: [
    { to: 's-1', kind: 'lexical', score: 1.0 },
    { to: '饿', kind: 'opposite', score: 1.0 }
  ],
  containing_sentences: ['s-1', 'wo-xihuan-chi'],
  created: '2026-06-27',
  updated: '2026-06-27',
  author_confirmed: true
};

const FAKE_WORD_NO_SENTENCES = {
  ...FAKE_WORD,
  id: 'lí',
  name: '离',
  containing_sentences: []
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function mockUnitApi(page: Page, unit: unknown) {
  // getUnit calls /api/units/{id}. Also mock /api/pinyin for HanziWithPinyin.
  page.route(/http:\/\/localhost:8000\/api\/units\//, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(unit) })
  );
  page.route(/http:\/\/localhost:8000\/api\/pinyin\//, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  );
}

function mockUnitApiError(page: Page, id: string) {
  page.route(new RegExp(`http://localhost:8000/api/units/${id}`), (route) =>
    route.fulfill({ status: 404, contentType: 'text/plain', body: `unit ${id} not found` })
  );
  page.route(/http:\/\/localhost:8000\/api\/pinyin\//, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  );
}

// ─── AC26: Unit detail page ───────────────────────────────────────────────────

test('AC26 — reads page.params.id and calls getUnit with it', async ({ page }) => {
  mockUnitApi(page, FAKE_SENTENCE);
  await page.goto('/unit/s-1');
  // Verify unit loaded via properties (hanzi in properties is always visible;
  // HanziWithPinyin text is async-loaded and tested separately in T4.)
  await expect(page.locator('[data-testid="unit-properties"]')).toContainText('我喜欢吃');
  await expect(page.locator('[data-testid="unit-type"]')).toContainText('sentence');
});

test('AC26 — shows unit properties (hanzi, pinyin, english, meaning)', async ({ page }) => {
  mockUnitApi(page, FAKE_SENTENCE);
  await page.goto('/unit/s-1');
  const props = page.locator('[data-testid="unit-properties"]');
  await expect(props).toContainText('我喜欢吃');
  await expect(props).toContainText('wǒ xǐhuān chī');
  await expect(props).toContainText('I like to eat');
  await expect(props).toContainText('expressing enjoyment of eating');
});

test('AC26 — renders groups as read-only chips, not CSV text', async ({ page }) => {
  mockUnitApi(page, FAKE_SENTENCE);
  await page.goto('/unit/s-1');
  // Use .first() since there may be multiple chips-readonly elements
  const chipsReadonly = page.locator('.chips-readonly').first();
  await expect(chipsReadonly).toBeVisible();
  const groupChip = page.locator('[data-testid="prop-groups-chip-food"]');
  await expect(groupChip).toBeVisible();
  await expect(groupChip).toContainText('food');
  const props = page.locator('[data-testid="unit-properties"]');
  await expect(props).not.toContainText('food,');
  await expect(props).not.toContainText(', food');
});

test('AC26 — groups connections by kind with a section per kind', async ({ page }) => {
  mockUnitApi(page, FAKE_SENTENCE);
  await page.goto('/unit/s-1');
  const lexSection = page.locator('[data-testid="connections-kind-lexical"]');
  const groupSection = page.locator('[data-testid="connections-kind-group"]');
  const semSection = page.locator('[data-testid="connections-kind-semantic"]');
  await expect(lexSection).toBeVisible();
  await expect(groupSection).toBeVisible();
  await expect(semSection).not.toBeVisible();
  await expect(lexSection).toContainText('chī');
  await expect(lexSection).toContainText('xǐhuān');
  await expect(groupSection).toContainText('food');
});

test('AC26 — word unit renders opposite-kind section', async ({ page }) => {
  mockUnitApi(page, FAKE_WORD);
  await page.goto('/unit/chī');
  await expect(page.locator('[data-testid="unit-type"]')).toContainText('word');
  const oppSection = page.locator('[data-testid="connections-kind-opposite"]');
  await expect(oppSection).toContainText('饿');
});

// ─── AC27: Word page lists containing sentences ───────────────────────────────

test('AC27 — word page lists containing sentences with links', async ({ page }) => {
  mockUnitApi(page, FAKE_WORD);
  await page.goto('/unit/chī');
  const section = page.locator('[data-testid="containing-sentences"]');
  await expect(section).toBeVisible();
  await expect(section).toContainText('Sentences containing this word');
  const links = section.locator('a[href^="/unit/"]');
  await expect(links).toHaveCount(2);
  await expect(links.nth(0)).toHaveAttribute('href', '/unit/s-1');
  await expect(links.nth(1)).toHaveAttribute('href', '/unit/wo-xihuan-chi');
});

test('AC27 — word page shows empty-state when no sentences contain it', async ({ page }) => {
  mockUnitApi(page, FAKE_WORD_NO_SENTENCES);
  await page.goto('/unit/lí');
  const section = page.locator('[data-testid="containing-sentences"]');
  await expect(section).toBeVisible();
  await expect(section.locator('[data-testid="no-containing"]')).toContainText(/not yet referenced/i);
});

test('AC27 — sentence and group pages do NOT show containing-sentences section', async ({ page }) => {
  mockUnitApi(page, FAKE_SENTENCE);
  await page.goto('/unit/s-1');
  await expect(page.locator('[data-testid="containing-sentences"]')).not.toBeVisible();
});

// ─── Error & navigation ────────────────────────────────────────────────────────

test('shows error message when getUnit fails', async ({ page }) => {
  mockUnitApiError(page, 'does-not-exist');
  await page.goto('/unit/does-not-exist');
  const errorEl = page.locator('.error');
  await expect(errorEl).toBeVisible();
  await expect(errorEl).toContainText('does-not-exist');
});

test('has a back link to the home page', async ({ page }) => {
  mockUnitApi(page, FAKE_SENTENCE);
  await page.goto('/unit/s-1');
  const back = page.locator('a.back');
  await expect(back).toHaveAttribute('href', '/');
});
