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
    { to: 's-1', kind: 'lexical', score: 1.0, name: '我喜欢吃' },
    { to: '饿', kind: 'opposite', score: 1.0, name: '饿' }
  ],
  containing_sentences: [{ id: 's-1', name: '我喜欢吃' }, { id: 'wo-xihuan-chi', name: '我喜欢吃和' }],
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

// ─── Connection + containing-sentence name enrichment ─────────────────────────

test('connections render name when present', async ({ page }) => {
  // Mock a unit whose connections carry the name field.
  mockUnitApi(page, {
    id: 'W5',
    type: 'word',
    name: '我',
    properties: { hanzi: '我', pinyin: 'wǒ', english: 'I/me', meaning: '', groups: [], antonyms: [] },
    connections: [
      { to: 'W6', kind: 'opposite', score: 1.0, name: '你' }
    ],
    created: '2026-07-01',
    updated: '2026-07-01',
    author_confirmed: true
  });
  await page.goto('/unit/W5');
  const link = page.locator('[data-testid="connections-kind-opposite"] a');
  await expect(link).toContainText('你');
  await expect(link).not.toContainText('W6');
});

test('connections fall back to id when name missing', async ({ page }) => {
  // Mock a unit whose connections have no name field (legacy shape).
  mockUnitApi(page, {
    id: 'W5',
    type: 'word',
    name: '我',
    properties: { hanzi: '我', pinyin: 'wǒ', english: 'I/me', meaning: '', groups: [], antonyms: [] },
    connections: [
      { to: 'W6', kind: 'opposite', score: 1.0 }
    ],
    created: '2026-07-01',
    updated: '2026-07-01',
    author_confirmed: true
  });
  await page.goto('/unit/W5');
  const link = page.locator('[data-testid="connections-kind-opposite"] a');
  // Falls back to bare id.
  await expect(link).toContainText('W6');
});

test('containing sentences render sentence name', async ({ page }) => {
  mockUnitApi(page, {
    id: 'W5',
    type: 'word',
    name: '我',
    properties: { hanzi: '我', pinyin: 'wǒ', english: 'I/me', meaning: '', groups: [], antonyms: [] },
    connections: [],
    containing_sentences: [
      { id: 'S1', name: '我喜欢吃' },
      { id: 'S2', name: '我是学生' }
    ],
    created: '2026-07-01',
    updated: '2026-07-01',
    author_confirmed: true
  });
  await page.goto('/unit/W5');
  const section = page.locator('[data-testid="containing-sentences"]');
  const links = section.locator('a');
  await expect(links).toHaveCount(2);
  await expect(links.nth(0)).toContainText('我喜欢吃');
  await expect(links.nth(1)).toContainText('我是学生');
});

test('click on connection navigates to that unit', async ({ page }) => {
  // Mock two units: s-1 (sentence) and W5 (word).
  // Uses a Map-based mock to return different units per id.
  const units = new Map<string, unknown>();
  units.set('s-1', {
    id: 's-1',
    type: 'sentence',
    name: '我喜欢吃',
    properties: {
      hanzi: '我喜欢吃', pinyin: 'wǒ xǐhuān chī', english: 'I like to eat',
      meaning: '', words: ['我', '喜欢', '吃'], word_refs: ['wǒ', 'xǐhuān', 'chī'],
      groups: [], antonyms: []
    },
    connections: [{ to: 'W5', kind: 'opposite', score: 1.0, name: '我' }],
    created: '2026-07-01', updated: '2026-07-01', author_confirmed: true
  });
  units.set('W5', {
    id: 'W5',
    type: 'word',
    name: '我',
    properties: {
      hanzi: '我', pinyin: 'wǒ', english: 'I/me', meaning: '',
      groups: [], antonyms: []
    },
    connections: [],
    created: '2026-07-01', updated: '2026-07-01', author_confirmed: true
  });
  // Intercept /api/units/ by extracting the id from the URL path.
  page.route(/\/api\/units\/(.+)/, (route) => {
    const url = new URL(route.request().url());
    const id = decodeURIComponent(url.pathname.replace('/api/units/', ''));
    const unit = units.get(id);
    if (unit) {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(unit) });
    } else {
      route.fulfill({ status: 404, contentType: 'text/plain', body: `unit ${id} not found` });
    }
  });
  // Also intercept pinyin so HanziWithPinyin resolves without errors.
  page.route(/\/api\/pinyin\/(.+)/, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  );

  await page.goto('/unit/s-1');
  // Wait for the unit properties section to confirm the page loaded.
  await expect(page.locator('[data-testid="unit-properties"]')).toBeVisible();
  // Verify URL is correct.
  await expect(page).toHaveURL(/\/unit\/s-1/);

  // Click the connection link to W5.
  await page.locator('[data-testid="connections-kind-opposite"] a').click();
  // Assert URL changed to W5.
  await expect(page).toHaveURL(/\/unit\/W5/);
  // Verify the new unit loaded (properties visible).
  await expect(page.locator('[data-testid="unit-properties"]')).toBeVisible();
});
