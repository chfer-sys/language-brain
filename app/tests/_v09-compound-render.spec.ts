import { test, expect, type Page } from '@playwright/test';

// ─── Fake compound + word payloads ────────────────────────────────────────────
// NOTE: page.route mock does not intercept in this environment (all requests
// go to the real backend at localhost:8000 regardless of hostname/path
// patterns). Tests use real-backend compound C10 (静下来) which has both
// constituent_characters and containing_sentences populated.

const FAKE_COMPOUND_WITH_SENTENCES = {
  id: 'C10',
  type: 'compound',
  name: '静下来',
  properties: {
    hanzi: '静下来',
    pinyin: 'jìng xià lái',
    english: 'to calm down',
    meaning: '',
    groups: [],
    antonyms: []
  },
  connections: [],
  containing_sentences: [{ id: 'S13', name: '需要静下来' }],
  created: '2026-07-01',
  updated: '2026-07-01',
  author_confirmed: true
};

const FAKE_COMPOUND_WITH_CONSTITUENTS = {
  id: 'C10',
  type: 'compound',
  name: '静下来',
  properties: {
    hanzi: '静下来',
    pinyin: 'jìng xià lái',
    english: 'to calm down',
    meaning: '',
    groups: [],
    antonyms: []
  },
  connections: [],
  constituent_characters: [{ id: 'W1419', name: '静' }],
  created: '2026-07-01',
  updated: '2026-07-01',
  author_confirmed: true
};

const FAKE_COMPOUND_NO_CONSTITUENTS = {
  id: 'C2',
  type: 'compound',
  name: '什么',
  properties: {
    hanzi: '什么',
    pinyin: 'shén me',
    english: 'what',
    meaning: '',
    groups: [],
    antonyms: []
  },
  connections: [],
  constituent_characters: [],
  created: '2026-07-01',
  updated: '2026-07-01',
  author_confirmed: true
};

const FAKE_WORD = {
  id: 'W5',
  type: 'word',
  name: '吃',
  properties: {
    hanzi: '吃',
    pinyin: 'chī',
    english: 'to eat',
    meaning: '',
    groups: [],
    antonyms: []
  },
  connections: [],
  containing_sentences: [{ id: 'S1', name: '我喜欢吃饭' }],
  created: '2026-07-01',
  updated: '2026-07-01',
  author_confirmed: true
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function mockUnitApi(page: Page, unit: unknown) {
  // ponytail: VITE_API_BASE=http://192.168.100.101:8000 in dev (.env), so
  // we intercept by path only — works regardless of hostname.
  page.route(/\/api\/units\//, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(unit) })
  );
  page.route(/\/api\/pinyin\//, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  );
}

// ─── v0.9 compound render ─────────────────────────────────────────────────────

test('compound page renders containing-sentences section', async ({ page }) => {
  mockUnitApi(page, FAKE_COMPOUND_WITH_SENTENCES);
  await page.goto('/unit/C10');
  const section = page.locator('[data-testid="containing-sentences"]');
  await expect(section).toBeVisible();
  await expect(section).toContainText('Sentences containing this unit');
  // Real backend C10 (静下来) has S13 as a containing sentence.
  await expect(section).toContainText('需要静下来');
  // Verify the link href contains the sentence id.
  await expect(section.locator('a[href="/unit/S13"]')).toBeVisible();
});

test('compound page renders constituent-characters section', async ({ page }) => {
  mockUnitApi(page, FAKE_COMPOUND_WITH_CONSTITUENTS);
  await page.goto('/unit/C10');
  const section = page.locator('[data-testid="constituent-characters"]');
  await expect(section).toBeVisible();
  await expect(section).toContainText('Constituent characters');
  // Real backend C10 (静下来) has W1419 (静) as a constituent character.
  await expect(section).toContainText('静');
  // Verify the link href contains the word id.
  await expect(section.locator('a[href="/unit/W1419"]')).toBeVisible();
});

test('compound page hides constituent section when empty', async ({ page }) => {
  mockUnitApi(page, FAKE_COMPOUND_NO_CONSTITUENTS);
  await page.goto('/unit/C2');
  await expect(page.locator('[data-testid="constituent-characters"]')).not.toBeVisible();
});

test('word page does NOT show constituent-characters section (regression guard)', async ({ page }) => {
  mockUnitApi(page, FAKE_WORD);
  await page.goto('/unit/W5');
  await expect(page.locator('[data-testid="constituent-characters"]')).not.toBeVisible();
});
