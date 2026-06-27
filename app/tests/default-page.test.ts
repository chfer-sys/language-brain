import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mount, unmount, tick } from 'svelte';
import Page from '../src/routes/+page.svelte';

// Mock the $lib/api module BEFORE importing the page so the page's
// `import { search } from '$lib/api'` picks up the mock. We expose
// `mockSearch` on `globalThis` so each test can configure its own
// return value and assertion.
const mockSearch = vi.fn();
vi.mock('../src/lib/api', () => ({
  search: (...args: unknown[]) => mockSearch(...args),
  suggest: vi.fn().mockResolvedValue([]),
  API_BASE: 'http://localhost:8000'
}));

const FAKE_RESULTS = [
  {
    id: 'chī',
    type: 'word' as const,
    name: '吃',
    snippet: 'chī',
    kinds: ['lexical' as const],
    score: 1.0
  },
  {
    id: 'chīfàn',
    type: 'word' as const,
    name: '吃饭',
    snippet: 'chīfàn',
    kinds: ['lexical' as const],
    score: 0.5
  },
  {
    id: 's-1',
    type: 'sentence' as const,
    name: '我喜欢吃',
    snippet: 'wǒ xǐhuān chī',
    kinds: ['lexical' as const],
    score: 0.25
  }
];

async function inputInto(target: HTMLElement, value: string) {
  const input = target.querySelector('input[type="search"]') as HTMLInputElement;
  input.value = value;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  await tick();
}

async function clickToggle(target: HTMLElement, testid: string, dataAttr: string, value: string) {
  const btn = target.querySelector(
    `[data-testid="${testid}"] [data-${dataAttr}="${value}"]`
  ) as HTMLButtonElement;
  btn.click();
  await tick();
}

// ----- AC22 + AC23 tests (carried over from T29) -----

describe('AC22 — default page still has a search box', () => {
  it('renders a search input as the primary above-the-fold control', () => {
    mockSearch.mockResolvedValue({ query: '', results: [] });
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    const input = target.querySelector('input[type="search"]');
    expect(input).toBeTruthy();

    unmount(component);
    target.remove();
  });
});

describe('AC23 — search debounce 200ms', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockSearch.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not call search immediately on keystroke', async () => {
    mockSearch.mockResolvedValue({ query: '吃', results: FAKE_RESULTS });
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });
    await inputInto(target, '吃');
    expect(mockSearch).not.toHaveBeenCalled();
    unmount(component);
    target.remove();
  });

  it('calls search exactly once after 200ms of debounce', async () => {
    mockSearch.mockResolvedValue({ query: '吃', results: FAKE_RESULTS });
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });
    await inputInto(target, '吃');
    await vi.advanceTimersByTimeAsync(199);
    expect(mockSearch).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(2);
    expect(mockSearch).toHaveBeenCalledTimes(1);
    expect(mockSearch).toHaveBeenCalledWith('吃', expect.objectContaining({
      kinds: expect.any(Array),
      types: expect.any(Array)
    }));
    unmount(component);
    target.remove();
  });

  it('passes all four kinds and all three types by default', async () => {
    mockSearch.mockResolvedValue({ query: '吃', results: FAKE_RESULTS });
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });
    await inputInto(target, '吃');
    await vi.advanceTimersByTimeAsync(200);
    expect(mockSearch).toHaveBeenCalledWith('吃', expect.objectContaining({
      kinds: expect.arrayContaining(['lexical', 'semantic', 'group', 'opposite']),
      types: expect.arrayContaining(['sentence', 'word', 'group'])
    }));
    unmount(component);
    target.remove();
  });
});

// ----- AC24 tests: kind-toggles + unit-type filters -----

describe('AC24 — kind-toggles and unit-type filters', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockSearch.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders four kind toggles (lexical, semantic, group, opposite) all on by default', async () => {
    mockSearch.mockResolvedValue({ query: '', results: [] });
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    // The control bar is hidden until there is a query, so type first.
    await inputInto(target, '吃');

    const toggles = target.querySelectorAll('[data-testid="kind-toggles"] [data-kind]');
    expect(toggles.length).toBe(4);
    const kinds = Array.from(toggles).map((t) => (t as HTMLElement).dataset.kind);
    expect(kinds).toEqual(['lexical', 'semantic', 'group', 'opposite']);
    for (const t of toggles) {
      expect(t.getAttribute('aria-pressed')).toBe('true');
    }

    unmount(component);
    target.remove();
  });

  it('renders three unit-type filters (sentence, word, group) all on by default', async () => {
    mockSearch.mockResolvedValue({ query: '', results: [] });
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    await inputInto(target, '吃');

    const filters = target.querySelectorAll('[data-testid="type-filters"] [data-type]');
    expect(filters.length).toBe(3);
    const types = Array.from(filters).map((t) => (t as HTMLElement).dataset.type);
    expect(types).toEqual(['sentence', 'word', 'group']);
    for (const f of filters) {
      expect(f.getAttribute('aria-pressed')).toBe('true');
    }

    unmount(component);
    target.remove();
  });

  it('clicking a kind toggle re-issues the search with the disabled kind omitted', async () => {
    mockSearch.mockResolvedValue({ query: '吃', results: FAKE_RESULTS });
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    await inputInto(target, '吃');
    await vi.advanceTimersByTimeAsync(200);
    expect(mockSearch).toHaveBeenCalledTimes(1);

    await clickToggle(target, 'kind-toggles', 'kind', 'semantic');
    await vi.advanceTimersByTimeAsync(200);
    expect(mockSearch).toHaveBeenCalledTimes(2);
    const lastCall = mockSearch.mock.calls[1];
    expect(lastCall[0]).toBe('吃');
    expect((lastCall[1] as { kinds: string[] }).kinds).not.toContain('semantic');
    expect((lastCall[1] as { kinds: string[] }).kinds).toContain('lexical');

    unmount(component);
    target.remove();
  });

  it('clicking a type filter re-issues the search with the disabled type omitted', async () => {
    mockSearch.mockResolvedValue({ query: '吃', results: FAKE_RESULTS });
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    await inputInto(target, '吃');
    await vi.advanceTimersByTimeAsync(200);
    expect(mockSearch).toHaveBeenCalledTimes(1);

    await clickToggle(target, 'type-filters', 'type', 'word');
    await vi.advanceTimersByTimeAsync(200);
    expect(mockSearch).toHaveBeenCalledTimes(2);
    const lastCall = mockSearch.mock.calls[1];
    expect((lastCall[1] as { types: string[] }).types).not.toContain('word');
    expect((lastCall[1] as { types: string[] }).types).toContain('sentence');

    unmount(component);
    target.remove();
  });

  it('does NOT trigger a full page reload when toggles are clicked (uses Svelte reactivity)', async () => {
    mockSearch.mockResolvedValue({ query: '吃', results: FAKE_RESULTS });
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    await inputInto(target, '吃');
    await vi.advanceTimersByTimeAsync(200);
    // Page URL does not change. We assert by checking that document.body
    // still contains our mount target (no navigation happened).
    expect(document.body.contains(target)).toBe(true);
    await clickToggle(target, 'kind-toggles', 'kind', 'lexical');
    expect(document.body.contains(target)).toBe(true);

    unmount(component);
    target.remove();
  });

  it('short-circuits to empty results when all kinds are toggled off (no network call)', async () => {
    mockSearch.mockResolvedValue({ query: '吃', results: FAKE_RESULTS });
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    await inputInto(target, '吃');
    await vi.advanceTimersByTimeAsync(200);
    expect(mockSearch).toHaveBeenCalledTimes(1);

    // Toggle off all four kinds.
    for (const k of ['semantic', 'group', 'opposite', 'lexical']) {
      await clickToggle(target, 'kind-toggles', 'kind', k);
    }
    await vi.advanceTimersByTimeAsync(200);
    // No new network call — search count unchanged.
    expect(mockSearch).toHaveBeenCalledTimes(1);

    // The status pane shows the "all filters off" message.
    const status = target.querySelector('.status');
    expect(status?.textContent).toMatch(/all filters off/i);

    unmount(component);
    target.remove();
  });
});