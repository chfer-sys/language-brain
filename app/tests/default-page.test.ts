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

const FAKE_RESULT = {
  id: 'chī',
  type: 'word' as const,
  name: '吃',
  snippet: 'chī',
  kinds: ['lexical' as const],
  score: 1.0
};

async function inputInto(target: HTMLElement, value: string) {
  const input = target.querySelector('input[type="search"]') as HTMLInputElement;
  input.value = value;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  await tick();
}

describe('AC22 — default page still has a search box', () => {
  it('renders a search input as the primary above-the-fold control', () => {
    mockSearch.mockResolvedValue({ query: '', results: [] });
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    const input = target.querySelector('input[type="search"]');
    expect(input).toBeTruthy();
    expect(input?.tagName).toBe('INPUT');

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
    mockSearch.mockResolvedValue({ query: '吃', results: [FAKE_RESULT] });

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    await inputInto(target, '吃');
    expect(mockSearch).not.toHaveBeenCalled();

    unmount(component);
    target.remove();
  });

  it('calls search exactly once after 200ms of debounce', async () => {
    mockSearch.mockResolvedValue({ query: '吃', results: [FAKE_RESULT] });

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    await inputInto(target, '吃');

    await vi.advanceTimersByTimeAsync(199);
    expect(mockSearch).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(2);
    expect(mockSearch).toHaveBeenCalledTimes(1);
    expect(mockSearch).toHaveBeenCalledWith('吃');

    unmount(component);
    target.remove();
  });

  it('coalesces multiple rapid keystrokes into a single search call', async () => {
    mockSearch.mockResolvedValue({ query: '我喜欢吃饭', results: [FAKE_RESULT] });

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    await inputInto(target, '我');
    await vi.advanceTimersByTimeAsync(30);
    await inputInto(target, '喜欢');
    await vi.advanceTimersByTimeAsync(40);
    await inputInto(target, '我喜欢吃');
    await vi.advanceTimersByTimeAsync(50);
    await inputInto(target, '我喜欢吃饭');
    await vi.advanceTimersByTimeAsync(30);

    expect(mockSearch).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(200);
    expect(mockSearch).toHaveBeenCalledTimes(1);
    expect(mockSearch).toHaveBeenCalledWith('我喜欢吃饭');

    unmount(component);
    target.remove();
  });

  it('clears results and skips search when input becomes empty', async () => {
    mockSearch.mockResolvedValue({ query: '吃', results: [FAKE_RESULT] });

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    await inputInto(target, '吃');
    await vi.advanceTimersByTimeAsync(200);
    expect(mockSearch).toHaveBeenCalledTimes(1);

    await inputInto(target, '');
    expect(mockSearch).toHaveBeenCalledTimes(1);

    const resultsEl = target.querySelector('[data-testid="results"]');
    expect(resultsEl).toBeNull();

    unmount(component);
    target.remove();
  });
});

describe('AC23 — results render after debounce fires', () => {
  beforeEach(() => {
    vi.useRealTimers();
    mockSearch.mockReset();
  });

  it('shows result rows in the pane once search returns', async () => {
    mockSearch.mockResolvedValue({ query: '吃', results: [FAKE_RESULT] });

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    await inputInto(target, '吃');
    await new Promise((r) => setTimeout(r, 250));
    await tick();

    const rows = target.querySelectorAll('[data-testid="result-row"]');
    expect(rows.length).toBe(1);
    expect(rows[0].textContent).toContain('吃');

    unmount(component);
    target.remove();
  });
});