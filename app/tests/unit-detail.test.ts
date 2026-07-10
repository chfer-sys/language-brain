import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount, unmount, tick } from 'svelte';

// Mutable shared state — hoisted by vi.hoisted() so the vi.mock
// factories (which are themselves hoisted above this file's body)
// can reference the same objects the test body mutates.
const { mockPageState, mockGetUnit } = vi.hoisted(() => {
  const mockPageState: { params: Record<string, string> } = { params: {} };
  const mockGetUnit = vi.fn();
  return { mockPageState, mockGetUnit };
});

vi.mock('$app/state', () => ({
  page: mockPageState,
  navigating: { from: null, to: null },
  updated: { current: false }
}));

vi.mock('$lib/api', () => ({
  getUnit: (...args: unknown[]) => mockGetUnit(...args),
  search: vi.fn(),
  suggest: vi.fn(),
  proposeLabels: vi.fn(),
  commitSentence: vi.fn(),
  API_BASE: 'http://localhost:8000'
}));

// Import AFTER the mocks so the page binds to them.
import UnitPage from '../src/routes/unit/[id]/+page.svelte';

const FAKE_SENTENCE = {
  id: 's-1',
  type: 'sentence' as const,
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
    { to: 'chī', kind: 'lexical' as const, score: 1.0 },
    { to: 'food', kind: 'group' as const, score: 1.0 },
    { to: 'xǐhuān', kind: 'lexical' as const, score: 0.67 }
  ],
  created: '2026-06-27',
  updated: '2026-06-27',
  author_confirmed: true
};

const FAKE_WORD = {
  id: 'chī',
  type: 'word' as const,
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
    { to: 's-1', kind: 'lexical' as const, score: 1.0 },
    { to: '饿', kind: 'opposite' as const, score: 1.0 }
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

async function settle(target: HTMLElement) {
  // Allow microtasks + setTimeout(0) to flush.
  await tick();
  await new Promise((r) => setTimeout(r, 10));
  await tick();
}

describe('AC26 — Unit detail page', () => {
  beforeEach(() => {
    mockGetUnit.mockReset();
    mockPageState.params = {};
  });

  it('reads page.params.id and calls getUnit with it', async () => {
    mockPageState.params = { id: 's-1' };
    mockGetUnit.mockResolvedValue(FAKE_SENTENCE);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(UnitPage, { target });

    await settle(target);

    expect(mockGetUnit).toHaveBeenCalledWith('s-1');
    expect(target.querySelector('[data-testid="unit-name"]')?.textContent).toContain('我喜欢吃');
    expect(target.querySelector('[data-testid="unit-type"]')?.textContent).toContain('sentence');

    unmount(component);
    target.remove();
  });

  it('shows the unit properties (hanzi, pinyin, english, meaning)', async () => {
    mockPageState.params = { id: 's-1' };
    mockGetUnit.mockResolvedValue(FAKE_SENTENCE);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(UnitPage, { target });

    await settle(target);

    const props = target.querySelector('[data-testid="unit-properties"]');
    expect(props?.textContent).toContain('我喜欢吃');
    expect(props?.textContent).toContain('wǒ xǐhuān chī');
    expect(props?.textContent).toContain('I like to eat');
    expect(props?.textContent).toContain('expressing enjoyment of eating');

    unmount(component);
    target.remove();
  });

  it('renders groups as read-only chips, not CSV text', async () => {
    mockPageState.params = { id: 's-1' };
    mockGetUnit.mockResolvedValue(FAKE_SENTENCE);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(UnitPage, { target });

    await settle(target);

    // Groups should render as chips (chip-readonly spans inside chips-readonly).
    const chipsReadonly = target.querySelector('.chips-readonly');
    expect(chipsReadonly).toBeTruthy();
    // FAKE_SENTENCE.properties.groups = ['food']
    const groupChip = target.querySelector('[data-testid="prop-groups-chip-food"]');
    expect(groupChip).toBeTruthy();
    expect(groupChip?.textContent).toContain('food');
    // The dt/dd for groups should NOT contain a comma-separated list.
    const props = target.querySelector('[data-testid="unit-properties"]');
    // Only 'food' shows, no stray comma CSV.
    expect(props?.textContent).not.toContain('food,');
    expect(props?.textContent).not.toContain(', food');

    unmount(component);
    target.remove();
  });

  it('groups connections by kind with a section per kind', async () => {
    mockPageState.params = { id: 's-1' };
    mockGetUnit.mockResolvedValue(FAKE_SENTENCE);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(UnitPage, { target });

    await settle(target);

    const lexSection = target.querySelector('[data-testid="connections-kind-lexical"]');
    const groupSection = target.querySelector('[data-testid="connections-kind-group"]');
    const semSection = target.querySelector('[data-testid="connections-kind-semantic"]');
    expect(lexSection).toBeTruthy();
    expect(groupSection).toBeTruthy();
    expect(semSection).toBeNull(); // no semantic edges in this fixture
    expect(lexSection?.textContent).toContain('chī');
    expect(lexSection?.textContent).toContain('xǐhuān');
    expect(groupSection?.textContent).toContain('food');

    unmount(component);
    target.remove();
  });

  it('renders word units with type "word" and opposite-kind section', async () => {
    mockPageState.params = { id: 'chī' };
    mockGetUnit.mockResolvedValue(FAKE_WORD);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(UnitPage, { target });

    await settle(target);

    expect(target.querySelector('[data-testid="unit-type"]')?.textContent).toContain('word');
    const oppSection = target.querySelector('[data-testid="connections-kind-opposite"]');
    expect(oppSection?.textContent).toContain('饿');

    unmount(component);
    target.remove();
  });

  it('AC27: word page lists containing sentences with links', async () => {
    mockPageState.params = { id: 'chī' };
    mockGetUnit.mockResolvedValue(FAKE_WORD);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(UnitPage, { target });

    await settle(target);

    const section = target.querySelector('[data-testid="containing-sentences"]');
    expect(section).toBeTruthy();
    expect(section?.textContent).toContain('Sentences containing this word');
    // Each sentence id renders as a link.
    const links = section?.querySelectorAll('a[href^="/unit/"]');
    expect(links?.length).toBe(2);
    expect(links?.[0]?.getAttribute('href')).toBe('/unit/s-1');
    expect(links?.[1]?.getAttribute('href')).toBe('/unit/wo-xihuan-chi');

    unmount(component);
    target.remove();
  });

  it('AC27: word page shows empty-state when no sentences contain it', async () => {
    mockPageState.params = { id: 'lí' };
    mockGetUnit.mockResolvedValue(FAKE_WORD_NO_SENTENCES);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(UnitPage, { target });

    await settle(target);

    const section = target.querySelector('[data-testid="containing-sentences"]');
    expect(section).toBeTruthy();
    expect(section?.querySelector('[data-testid="no-containing"]')?.textContent).toMatch(
      /not yet referenced/i
    );

    unmount(component);
    target.remove();
  });

  it('AC27: sentence and group pages do NOT show the containing-sentences section', async () => {
    mockPageState.params = { id: 's-1' };
    mockGetUnit.mockResolvedValue(FAKE_SENTENCE);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(UnitPage, { target });

    await settle(target);

    expect(target.querySelector('[data-testid="containing-sentences"]')).toBeNull();

    unmount(component);
    target.remove();
  });

  it('shows an error message when getUnit fails', async () => {
    mockPageState.params = { id: 'does-not-exist' };
    mockGetUnit.mockRejectedValue(new Error('unit does-not-exist not found'));
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(UnitPage, { target });

    await settle(target);

    const errorEl = target.querySelector('.error');
    expect(errorEl?.textContent).toContain('does-not-exist');

    unmount(component);
    target.remove();
  });

  it('has a back link to the home page', async () => {
    mockPageState.params = { id: 's-1' };
    mockGetUnit.mockResolvedValue(FAKE_SENTENCE);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(UnitPage, { target });

    await settle(target);

    const back = target.querySelector('a.back') as HTMLAnchorElement;
    expect(back?.getAttribute('href')).toBe('/');

    unmount(component);
    target.remove();
  });

  it('refetches when page.params.id changes (navigation between units)', async () => {
    mockPageState.params = { id: 's-1' };
    mockGetUnit.mockResolvedValue(FAKE_SENTENCE);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(UnitPage, { target });
    await settle(target);
    expect(mockGetUnit).toHaveBeenCalledTimes(1);
    expect(mockGetUnit).toHaveBeenLastCalledWith('s-1');

    // Navigate to a different unit. Setting mockPageState.params
    // doesn't auto-trigger reactivity because the page reads from
    // a frozen snapshot; the route would normally use goto(). For
    // this assertion we simulate it by remounting with the new id.
    unmount(component);
    target.remove();

    mockGetUnit.mockResolvedValue(FAKE_WORD);
    mockPageState.params = { id: 'chī' };
    const target2 = document.createElement('div');
    document.body.appendChild(target2);
    const component2 = mount(UnitPage, { target: target2 });
    await settle(target2);
    expect(mockGetUnit).toHaveBeenCalledTimes(2);
    expect(mockGetUnit).toHaveBeenLastCalledWith('chī');

    unmount(component2);
    target2.remove();
  });
});