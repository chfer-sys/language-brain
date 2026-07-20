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
  containing_sentences: [{ id: 's-1', name: '我喜欢吃' }],
  created: '2026-06-27',
  updated: '2026-06-27',
  author_confirmed: true
};

const FAKE_COMPOUND = {
  id: 'c-1',
  type: 'compound',
  name: '吃饭',
  properties: {
    hanzi: '吃饭',
    pinyin: 'chī fàn',
    english: 'to have a meal',
    meaning: 'the act of eating rice / having a meal',
    groups: ['food'],
    antonyms: []
  },
  connections: [],
  created: '2026-06-27',
  updated: '2026-06-27',
  author_confirmed: true
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function mockUnit(page: Page, unit: unknown) {
  page.route(/http:\/\/localhost:8000\/api\/units\//, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(unit) })
  );
  page.route(/http:\/\/localhost:8000\/api\/pinyin\//, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  );
  // ponytail: suggest endpoint for existingGroups autocomplete in edit mode
  page.route(/http:\/\/localhost:8000\/api\/search\/suggest/, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  );
}

// ─── AC TBD: Sentence edit ────────────────────────────────────────────────────

test('sentence page shows Edit button', async ({ page }) => {
  mockUnit(page, FAKE_SENTENCE);
  await page.goto('/unit/s-1');
  await expect(page.locator('[data-testid="edit-btn"]')).toBeVisible();
});

test('sentence: clicking Edit shows form with fields pre-filled', async ({ page }) => {
  mockUnit(page, FAKE_SENTENCE);
  await page.goto('/unit/s-1');
  await page.locator('[data-testid="edit-btn"]').click();
  await expect(page.locator('[data-testid="edit-form"]')).toBeVisible();
  await expect(page.locator('[data-testid="edit-hanzi-display"]')).toContainText('我喜欢吃');
  await expect(page.locator('[data-testid="edit-pinyin"]')).toHaveValue('wǒ xǐhuān chī');
  await expect(page.locator('[data-testid="edit-english"]')).toHaveValue('I like to eat');
  await expect(page.locator('[data-testid="edit-meaning"]')).toHaveValue('expressing enjoyment of eating');
  // words is CSV
  await expect(page.locator('[data-testid="edit-words"]')).toHaveValue('我, 喜欢, 吃');
  await expect(page.locator('[data-testid="save-edit-btn"]')).toBeVisible();
  await expect(page.locator('[data-testid="cancel-edit-btn"]')).toBeVisible();
});

test('sentence: Save calls PUT /api/sentences/{id} with correct body', async ({ page }) => {
  let savedBody: Record<string, unknown> | null = null;
  page.route(/http:\/\/localhost:8000\/api\/sentences\/s-1/, (route) => {
    if (route.request().method() === 'PUT') {
      savedBody = route.request().postData() ? JSON.parse(route.request().postData()!) : null;
    }
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 's-1', updated: '2026-07-21', connections_summary: {}, groups_added: [], groups_removed: [] })
    });
  });
  page.route(/http:\/\/localhost:8000\/api\/units\/s-1/, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FAKE_SENTENCE) })
  );
  page.route(/http:\/\/localhost:8000\/api\/pinyin\//, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  );
  page.route(/http:\/\/localhost:8000\/api\/search\/suggest/, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  );

  await page.goto('/unit/s-1');
  await page.locator('[data-testid="edit-btn"]').click();
  await page.locator('[data-testid="edit-english"]').fill('I really like to eat');
  await page.locator('[data-testid="save-edit-btn"]').click();
  await page.waitForTimeout(500);

  expect(savedBody).not.toBeNull();
  expect(savedBody!['hanzi']).toBe('我喜欢吃');
  expect(savedBody!['english']).toBe('I really like to eat');
  expect(savedBody!['pinyin']).toBe('wǒ xǐhuān chī');
  expect(savedBody!['words']).toEqual(['我', '喜欢', '吃']);
});

test('sentence: Cancel hides form without calling any endpoint', async ({ page }) => {
  let anyPut = false;
  page.route(/http:\/\/localhost:8000\/api\/sentences\//, (route) => {
    if (route.request().method() === 'PUT') anyPut = true;
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });
  mockUnit(page, FAKE_SENTENCE);
  await page.goto('/unit/s-1');
  await page.locator('[data-testid="edit-btn"]').click();
  await page.locator('[data-testid="edit-english"]').fill('changed');
  await page.locator('[data-testid="cancel-edit-btn"]').click();
  await expect(page.locator('[data-testid="edit-form"]')).not.toBeVisible();
  expect(anyPut).toBe(false);
});

// ─── Word edit ────────────────────────────────────────────────────────────────

test('word page shows Edit button', async ({ page }) => {
  mockUnit(page, FAKE_WORD);
  await page.goto('/unit/chī');
  await expect(page.locator('[data-testid="edit-btn"]')).toBeVisible();
});

test('word: clicking Edit shows form with fields pre-filled', async ({ page }) => {
  mockUnit(page, FAKE_WORD);
  await page.goto('/unit/chī');
  await page.locator('[data-testid="edit-btn"]').click();
  await expect(page.locator('[data-testid="edit-form"]')).toBeVisible();
  await expect(page.locator('[data-testid="edit-english"]')).toHaveValue('to eat');
  await expect(page.locator('[data-testid="edit-meaning"]')).toHaveValue('the act of eating');
  await expect(page.locator('[data-testid="save-edit-btn"]')).toBeVisible();
  await expect(page.locator('[data-testid="cancel-edit-btn"]')).toBeVisible();
});

// ─── Compound edit ────────────────────────────────────────────────────────────

test('compound page shows Edit button', async ({ page }) => {
  mockUnit(page, FAKE_COMPOUND);
  await page.goto('/unit/c-1');
  await expect(page.locator('[data-testid="edit-btn"]')).toBeVisible();
});

test('compound: clicking Edit shows form with same fields as word', async ({ page }) => {
  mockUnit(page, FAKE_COMPOUND);
  await page.goto('/unit/c-1');
  await page.locator('[data-testid="edit-btn"]').click();
  await expect(page.locator('[data-testid="edit-form"]')).toBeVisible();
  // compound form has english, meaning, groups, antonyms — same as word
  await expect(page.locator('[data-testid="edit-english"]')).toHaveValue('to have a meal');
  await expect(page.locator('[data-testid="edit-meaning"]')).toHaveValue('the act of eating rice / having a meal');
  await expect(page.locator('[data-testid="save-edit-btn"]')).toBeVisible();
  await expect(page.locator('[data-testid="cancel-edit-btn"]')).toBeVisible();
});
