import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount, unmount, tick } from 'svelte';
import HanziWithPinyin from '../src/lib/components/HanziWithPinyin.svelte';

const FAKE_PINYIN: Record<string, { char: string; pinyin: string; tone: number }[]> = {
  '你好': [
    { char: '你', pinyin: 'nǐ', tone: 3 },
    { char: '好', pinyin: 'hǎo', tone: 3 }
  ],
  '我流口水了': [
    { char: '我', pinyin: 'wǒ', tone: 3 },
    { char: '流', pinyin: 'liú', tone: 2 },
    { char: '口', pinyin: 'kǒu', tone: 3 },
    { char: '水', pinyin: 'shuǐ', tone: 3 },
    { char: '了', pinyin: 'le', tone: 5 }
  ]
};

beforeEach(() => {
  // Clear module-level cache between tests so we don't accidentally
  // serve stale responses.
  (globalThis as unknown as { __lb_pinyin_cache?: Map<string, unknown> }).__lb_pinyin_cache?.clear();

  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const u = new URL(url, 'http://localhost');
      const text = decodeURIComponent(u.pathname.replace(/^\/api\/pinyin\//, ''));
      const data = FAKE_PINYIN[text] ?? text.split('').map((c) => ({ char: c, pinyin: '', tone: 5 }));
      return {
        ok: true,
        status: 200,
        json: async () => data
      } as Response;
    })
  );
});

async function renderAndSettle(text: string, testid = 'hanzi') {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const component = mount(HanziWithPinyin, { target, props: { text, testid } });
  // The component sets entries asynchronously after fetch resolves.
  // Advance a few ticks so the await chains complete.
  await new Promise((r) => setTimeout(r, 5));
  await tick();
  return { target, component };
}

describe('Note 4 / T4 — HanziWithPinyin (pinyin-on-hover + tone color)', () => {
  it('renders one span per character with the right tone class', async () => {
    const { target, component } = await renderAndSettle('你好');
    const chars = target.querySelectorAll('.hanzi-char');
    expect(chars.length).toBe(2);
    expect(chars[0].textContent).toBe('你');
    expect(chars[0].classList.contains('tone-3')).toBe(true);
    expect(chars[1].textContent).toBe('好');
    expect(chars[1].classList.contains('tone-3')).toBe(true);
    unmount(component);
    target.remove();
  });

  it('sets a native tooltip (title) with the pinyin on each char', async () => {
    const { target, component } = await renderAndSettle('你好');
    const chars = target.querySelectorAll('.hanzi-char');
    expect(chars[0].getAttribute('title')).toBe('nǐ');
    expect(chars[1].getAttribute('title')).toBe('hǎo');
    unmount(component);
    target.remove();
  });

  it('exposes tone and pinyin as data attributes for tests / CSS hooks', async () => {
    const { target, component } = await renderAndSettle('我流口水了');
    const chars = target.querySelectorAll('.hanzi-char');
    // 我 — tone 3
    expect(chars[0].getAttribute('data-tone')).toBe('3');
    expect(chars[0].getAttribute('data-pinyin')).toBe('wǒ');
    // 流 — tone 2
    expect(chars[1].getAttribute('data-tone')).toBe('2');
    expect(chars[1].getAttribute('data-pinyin')).toBe('liú');
    // 了 — tone 5 (neutral)
    expect(chars[4].getAttribute('data-tone')).toBe('5');
    expect(chars[4].getAttribute('data-pinyin')).toBe('le');
    unmount(component);
    target.remove();
  });

  it('fetches /api/pinyin/{text} on mount', async () => {
    const fetchSpy = vi.mocked(fetch);
    const { target, component } = await renderAndSettle('你好');
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const url = fetchSpy.mock.calls[0][0] as string;
    expect(url).toContain('/api/pinyin/');
    expect(url).toContain(encodeURIComponent('你好'));
    unmount(component);
    target.remove();
  });

  it('handles empty text without fetching or rendering spans', async () => {
    const fetchSpy = vi.mocked(fetch);
    const { target, component } = await renderAndSettle('');
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(target.querySelectorAll('.hanzi-char').length).toBe(0);
    unmount(component);
    target.remove();
  });

  it('falls back to plain text per character when the fetch fails', async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        // Throw a TypeError to trigger the catch block in the
        // component (the component does !res.ok check + JSON parse,
        // but a thrown TypeError from fetch itself exercises the
        // catch path more reliably).
        throw new TypeError('network down');
      })
    );
    const { target, component } = await renderAndSettle('你好');
    const chars = target.querySelectorAll('.hanzi-char');
    expect(chars.length).toBe(2);
    // Falls back to plain (no tone class).
    expect(chars[0].classList.contains('tone-3')).toBe(false);
    expect(chars[0].classList.contains('plain')).toBe(true);
    unmount(component);
    target.remove();
  });
});
