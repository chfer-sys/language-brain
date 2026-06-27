import { describe, it, expect } from 'vitest';
import { mount, unmount } from 'svelte';
import Page from '../src/routes/+page.svelte';

// AC22: The default page (`/`) renders a search box and no other content above the fold.
// We use Svelte 5's raw `mount` API (recommended for vitest) instead of
// @testing-library/svelte because the latter has unresolved Svelte 5 +
// Vitest condition-resolution issues that are not worth blocking T28 on.
// Tradeoff: we lose @testing-library/dom's getByRole helpers, but AC22
// only requires asserting a small set of structural facts about the page,
// all of which are expressible via direct DOM queries.

describe('AC22 — default page is a search box above the fold', () => {
  it('renders a search input as the primary control', () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    const input = target.querySelector('input[type="search"]');
    expect(input).toBeTruthy();
    expect(input?.tagName).toBe('INPUT');

    unmount(component);
    target.remove();
  });

  it('renders the bilingual brand above the search box', () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    const brand = target.querySelector('.brand');
    expect(brand).toBeTruthy();
    expect(brand?.textContent).toContain('Language Brain');
    expect(brand?.textContent).toContain('语言大脑');

    // The brand must come before the search input in DOM order.
    const all = Array.from(target.querySelectorAll('.brand, .search-row input'));
    const brandIdx = all.findIndex((el) => el.classList.contains('brand'));
    const inputIdx = all.findIndex((el) => el.tagName === 'INPUT');
    expect(brandIdx).toBeGreaterThanOrEqual(0);
    expect(inputIdx).toBeGreaterThan(brandIdx);

    unmount(component);
    target.remove();
  });

  it('renders the "+ Add sentence" link pointing at /add', () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    const link = Array.from(target.querySelectorAll('a')).find(
      (a) => a.textContent?.trim() === '+ Add sentence'
    );
    expect(link).toBeTruthy();
    expect(link?.getAttribute('href')).toBe('/add');

    unmount(component);
    target.remove();
  });

  it('does not render T29–T33 placeholder components (results, toggles, filters, form)', () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    // Stub components render placeholder text containing their name.
    // None of those strings should appear in T28's DOM.
    const text = target.textContent ?? '';
    expect(text).not.toContain('KindToggles');
    expect(text).not.toContain('UnitTypeFilters');
    expect(text).not.toContain('AddSentenceForm');

    unmount(component);
    target.remove();
  });

  it('uses the AC22 placeholder text from design-t28.md §2.3 (option D: examples by example)', () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(Page, { target });

    const input = target.querySelector('input[type="search"]') as HTMLInputElement | null;
    expect(input?.placeholder).toBe('Try: 看起来好吃 or 吃 or basic-verbs');

    unmount(component);
    target.remove();
  });
});