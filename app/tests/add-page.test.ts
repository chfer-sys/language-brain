import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount, unmount, tick } from 'svelte';

const mockProposeLabels = vi.fn();
const mockCommitSentence = vi.fn();

vi.mock('$lib/api', () => ({
  proposeLabels: (...args: unknown[]) => mockProposeLabels(...args),
  commitSentence: (...args: unknown[]) => mockCommitSentence(...args),
  suggest: vi.fn().mockResolvedValue([]),
  search: vi.fn().mockResolvedValue({ query: '', results: [] }),
  getUnit: vi.fn().mockResolvedValue(null),
  API_BASE: 'http://localhost:8000'
}));

// Import AFTER the mock so the page binds to the mocked functions.
import AddPage from '../src/routes/add/+page.svelte';

const FAKE_LABELS = {
  pinyin: 'wǒ liú kǒu shuǐ le',
  english: "I'm drooling",
  meaning: 'visual craving: I see food and my mouth waters',
  words: ['我', '流', '口水', '了'],
  word_refs: ['wǒ', 'liú', 'kǒushuǐ', 'le'],
  groups: [
    { id: 'reactions', display_name: 'reactions', description: '' },
    { id: 'food', display_name: 'food', description: '' }
  ],
  antonyms: []
};

async function setInputValue(target: HTMLElement, selector: string, value: string) {
  const el = target.querySelector(selector) as HTMLInputElement | HTMLTextAreaElement;
  el.value = value;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  await tick();
}

async function clickButton(target: HTMLElement, testid: string) {
  const btn = target.querySelector(`[data-testid="${testid}"]`) as HTMLButtonElement;
  btn.click();
  await tick();
}

describe('AC25 — Add-sentence page propose-labels flow', () => {
  beforeEach(() => {
    mockProposeLabels.mockReset();
    mockCommitSentence.mockReset();
  });

  it('renders the hanzi textarea, optional note, and Propose-labels button', () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    expect(target.querySelector('[data-testid="hanzi-input"]')).toBeTruthy();
    expect(target.querySelector('[data-testid="propose-btn"]')).toBeTruthy();
    expect(target.querySelector('input[type="text"]')).toBeTruthy();

    unmount(component);
    target.remove();
  });

  it('disables the Propose button when hanzi is empty', async () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    const btn = target.querySelector('[data-testid="propose-btn"]') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);

    await setInputValue(target, '[data-testid="hanzi-input"]', '我');
    expect(btn.disabled).toBe(false);

    unmount(component);
    target.remove();
  });

  it('calls proposeLabels and renders editable fields when the AI responds', async () => {
    mockProposeLabels.mockResolvedValue(FAKE_LABELS);

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    await setInputValue(target, '[data-testid="hanzi-input"]', '我流口水了');
    await clickButton(target, 'propose-btn');

    expect(mockProposeLabels).toHaveBeenCalledWith('我流口水了', '');
    expect(target.querySelector('[data-testid="proposed-form"]')).toBeTruthy();

    const pinyin = target.querySelector('[data-testid="pinyin-input"]') as HTMLInputElement;
    expect(pinyin.value).toBe(FAKE_LABELS.pinyin);

    // All seven editable fields populated.
    const inputs = target.querySelectorAll('[data-testid="proposed-form"] input');
    expect(inputs.length).toBe(7);

    unmount(component);
    target.remove();
  });

  it('passes the English note to proposeLabels when the user typed one', async () => {
    mockProposeLabels.mockResolvedValue(FAKE_LABELS);

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    await setInputValue(target, '[data-testid="hanzi-input"]', '我流口水了');
    // Second input is the English note (after hanzi textarea).
    const noteInput = target.querySelectorAll('input[type="text"]')[0] as HTMLInputElement;
    noteInput.value = 'drooling over food';
    noteInput.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();

    await clickButton(target, 'propose-btn');
    expect(mockProposeLabels).toHaveBeenCalledWith('我流口水了', 'drooling over food');

    unmount(component);
    target.remove();
  });

  it('allows the user to edit proposed fields before saving', async () => {
    mockProposeLabels.mockResolvedValue(FAKE_LABELS);

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    await setInputValue(target, '[data-testid="hanzi-input"]', '我流口水了');
    await clickButton(target, 'propose-btn');

    // User edits the meaning field (third input in the proposed form).
    const meaningInput = target.querySelectorAll('[data-testid="proposed-form"] input')[2] as HTMLInputElement;
    meaningInput.value = 'user-edited meaning';
    meaningInput.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();

    mockCommitSentence.mockResolvedValue({
      id: 'wo-liu-kou-shui-le',
      saved_at: '2026-06-27',
      word_ids_created: [],
      group_ids_created: []
    });
    await clickButton(target, 'save-btn');

    expect(mockCommitSentence).toHaveBeenCalledTimes(1);
    const body = mockCommitSentence.mock.calls[0][0] as Record<string, unknown>;
    expect(body.meaning).toBe('user-edited meaning');
    expect(body.pinyin).toBe(FAKE_LABELS.pinyin);

    unmount(component);
    target.remove();
  });

  it('renders a Saved confirmation after commit succeeds', async () => {
    mockProposeLabels.mockResolvedValue(FAKE_LABELS);
    mockCommitSentence.mockResolvedValue({
      id: 'wo-liu-kou-shui-le',
      saved_at: '2026-06-27',
      word_ids_created: [],
      group_ids_created: []
    });

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    await setInputValue(target, '[data-testid="hanzi-input"]', '我流口水了');
    await clickButton(target, 'propose-btn');
    await clickButton(target, 'save-btn');

    const saved = target.querySelector('[data-testid="saved"]');
    expect(saved).toBeTruthy();
    expect(saved?.textContent).toContain('wo-liu-kou-shui-le');

    unmount(component);
    target.remove();
  });

  it('shows an error message if propose fails', async () => {
    mockProposeLabels.mockRejectedValue(new Error('AI provider unavailable'));

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    await setInputValue(target, '[data-testid="hanzi-input"]', '我流口水了');
    await clickButton(target, 'propose-btn');
    // Wait for the async propose to settle.
    await new Promise((r) => setTimeout(r, 10));
    await tick();

    const errorEl = target.querySelector('.error');
    expect(errorEl).toBeTruthy();
    expect(errorEl?.textContent ?? '').toContain('AI provider unavailable');
    // No proposed form should be rendered on failure.
    expect(target.querySelector('[data-testid="proposed-form"]')).toBeNull();

    unmount(component);
    target.remove();
  });

  it('returns a Back link to the home page', () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    const back = target.querySelector('a.back') as HTMLAnchorElement;
    expect(back?.getAttribute('href')).toBe('/');

    unmount(component);
    target.remove();
  });

  // ---------------------------------------------------------------------
  // T1 (Note 1): English hint authoritative
  // ---------------------------------------------------------------------

  it('pre-fills the English field from the typed hint (Note 1: authoritative)', async () => {
    mockProposeLabels.mockResolvedValue(FAKE_LABELS);

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    await setInputValue(target, '[data-testid="hanzi-input"]', '我流口水了');
    const noteInput = target.querySelectorAll('input[type="text"]')[0] as HTMLInputElement;
    noteInput.value = 'drooling over food';
    noteInput.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();

    await clickButton(target, 'propose-btn');

    // English field should contain the user's hint, NOT the AI's draft.
    const english = target.querySelector('[data-testid="english-input"]') as HTMLInputElement;
    expect(english.value).toBe('drooling over food');

    // The AI's draft should be visible as a "compare with AI" hint.
    const proposedForm = target.querySelector('[data-testid="proposed-form"]') as HTMLElement;
    expect(proposedForm.textContent).toContain("AI suggested");
    expect(proposedForm.textContent).toContain(FAKE_LABELS.english);

    unmount(component);
    target.remove();
  });

  it('sends the user-edited English field to commitSentence (not the AI draft)', async () => {
    mockProposeLabels.mockResolvedValue(FAKE_LABELS);
    mockCommitSentence.mockResolvedValue({
      id: 'wo-liu-kou-shui-le',
      saved_at: '2026-06-27',
      word_ids_created: [],
      group_ids_created: []
    });

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    await setInputValue(target, '[data-testid="hanzi-input"]', '我流口水了');
    await clickButton(target, 'propose-btn');

    // User edits the English field (was pre-filled from hint, or empty).
    const english = target.querySelector('[data-testid="english-input"]') as HTMLInputElement;
    english.value = 'final english I wrote';
    english.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();

    await clickButton(target, 'save-btn');

    const body = mockCommitSentence.mock.calls[0][0] as Record<string, unknown>;
    expect(body.english).toBe('final english I wrote');

    unmount(component);
    target.remove();
  });

  it('hides the AI-suggested hint when the user matches the AI draft', async () => {
    mockProposeLabels.mockResolvedValue(FAKE_LABELS);

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    await setInputValue(target, '[data-testid="hanzi-input"]', '我流口水了');
    const noteInput = target.querySelectorAll('input[type="text"]')[0] as HTMLInputElement;
    // User happens to type the same text as the AI draft.
    noteInput.value = FAKE_LABELS.english;
    noteInput.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();

    await clickButton(target, 'propose-btn');

    const proposedForm = target.querySelector('[data-testid="proposed-form"]') as HTMLElement;
    // The compare-with-AI hint should NOT appear when the values match.
    expect(proposedForm.textContent).not.toContain('AI suggested');

    unmount(component);
    target.remove();
  });

  // ---------------------------------------------------------------------
  // T2 (Note 3): Antonym chip editor — bare hanzi, not pinyin
  // ---------------------------------------------------------------------

  it('renders the antonyms field as a chip editor, not a CSV text input', async () => {
    mockProposeLabels.mockResolvedValue(FAKE_LABELS);

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    await setInputValue(target, '[data-testid="hanzi-input"]', '我流口水了');
    await clickButton(target, 'propose-btn');

    expect(target.querySelector('[data-testid="antonyms-editor"]')).toBeTruthy();
    expect(target.querySelector('[data-testid="antonyms-input"]')).toBeTruthy();

    unmount(component);
    target.remove();
  });

  it('seeds the chip editor from the AI\'s proposed antonym hanzi', async () => {
    mockProposeLabels.mockResolvedValue({
      ...FAKE_LABELS,
      antonyms: ['饱', '热']
    });

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    await setInputValue(target, '[data-testid="hanzi-input"]', '我流口水了');
    await clickButton(target, 'propose-btn');

    expect(target.querySelector('[data-testid="antonyms-chip-饱"]')).toBeTruthy();
    expect(target.querySelector('[data-testid="antonyms-chip-热"]')).toBeTruthy();

    unmount(component);
    target.remove();
  });

  it('lets the user add an antonym chip by typing + Enter', async () => {
    mockProposeLabels.mockResolvedValue(FAKE_LABELS);

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    await setInputValue(target, '[data-testid="hanzi-input"]', '我流口水了');
    await clickButton(target, 'propose-btn');

    const chipInput = target.querySelector('[data-testid="antonyms-input"]') as HTMLInputElement;
    chipInput.value = '冷';
    chipInput.dispatchEvent(new Event('input', { bubbles: true }));
    chipInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await tick();

    expect(target.querySelector('[data-testid="antonyms-chip-冷"]')).toBeTruthy();

    unmount(component);
    target.remove();
  });

  it('lets the user remove an antonym chip by clicking its × button', async () => {
    mockProposeLabels.mockResolvedValue({
      ...FAKE_LABELS,
      antonyms: ['饱', '热']
    });

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    await setInputValue(target, '[data-testid="hanzi-input"]', '我流口水了');
    await clickButton(target, 'propose-btn');

    expect(target.querySelector('[data-testid="antonyms-chip-饱"]')).toBeTruthy();

    const chip = target.querySelector('[data-testid="antonyms-chip-饱"]') as HTMLElement;
    const removeBtn = chip.querySelector('button.chip-remove') as HTMLButtonElement;
    removeBtn.click();
    await tick();

    expect(target.querySelector('[data-testid="antonyms-chip-饱"]')).toBeNull();
    expect(target.querySelector('[data-testid="antonyms-chip-热"]')).toBeTruthy();

    unmount(component);
    target.remove();
  });

  it('sends the edited antonym chips (hanzi) to commitSentence', async () => {
    mockProposeLabels.mockResolvedValue({ ...FAKE_LABELS, antonyms: ['饱', '热'] });
    mockCommitSentence.mockResolvedValue({
      id: 'wo-liu-kou-shui-le',
      saved_at: '2026-06-27',
      word_ids_created: [],
      group_ids_created: []
    });

    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(AddPage, { target });

    await setInputValue(target, '[data-testid="hanzi-input"]', '我流口水了');
    await clickButton(target, 'propose-btn');

    const chipInput = target.querySelector('[data-testid="antonyms-input"]') as HTMLInputElement;
    chipInput.value = '冷';
    chipInput.dispatchEvent(new Event('input', { bubbles: true }));
    chipInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await tick();

    const removeBtn = (
      target.querySelector('[data-testid="antonyms-chip-热"]') as HTMLElement
    ).querySelector('button.chip-remove') as HTMLButtonElement;
    removeBtn.click();
    await tick();

    await clickButton(target, 'save-btn');

    expect(mockCommitSentence).toHaveBeenCalledTimes(1);
    const body = mockCommitSentence.mock.calls[0][0] as Record<string, unknown>;
    const sent = body.antonyms as string[];
    expect(sent).toContain('饱');
    expect(sent).toContain('冷');
    expect(sent).not.toContain('热');
  });
});