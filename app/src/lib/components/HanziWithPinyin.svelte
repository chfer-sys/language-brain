<script lang="ts">
  /**
   * Renders a hanzi string with per-character pinyin tooltips and
   * tone-colored underlines (Note 4 / T4 of v0.4-backlog).
   *
   * For each character in the input string:
   *   - If pinyin is non-empty: render the character with a tone-
   *     colored underline + a `title` attribute (native browser
   *     tooltip fallback) and a custom tooltip on hover/focus.
   *   - If pinyin is empty (punctuation, ASCII, unknown chars):
   *     render as plain text without any decoration.
   *
   * Tone colors:
   *   tone 1: red    (#dc2626)
   *   tone 2: orange (#ea580c)
   *   tone 3: green  (#16a34a)
   *   tone 4: blue   (#2563eb)
   *   tone 5: gray   (#9ca3af) — neutral
   *
   * The component fetches /api/pinyin/{text} on mount and caches
   * per-text results in a module-level map so multiple usages of
   * the same string don't re-hit the network.
   */
  import { onMount } from 'svelte';
  import { API_BASE } from '$lib/api';

  export let text: string = '';
  export let testid: string = 'hanzi-with-pinyin';

  type PinyinEntry = { char: string; pinyin: string; tone: number };
  type PinyinMap = Map<string, PinyinEntry[]>;

  // Module-level cache so multiple HanziWithPinyin instances on the
  // same page share results.
  const _cache: PinyinMap = (globalThis as unknown as { __lb_pinyin_cache?: PinyinMap }).__lb_pinyin_cache
    ?? ((globalThis as unknown as { __lb_pinyin_cache: PinyinMap }).__lb_pinyin_cache = new Map());

  let entries: PinyinEntry[] = [];
  let loading = true;
  let error: string | null = null;

  async function load(t: string): Promise<void> {
    if (t.length === 0) {
      entries = [];
      loading = false;
      return;
    }
    const cached = _cache.get(t);
    if (cached) {
      entries = cached;
      loading = false;
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/pinyin/${encodeURIComponent(t)}`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data: PinyinEntry[] = await res.json();
      _cache.set(t, data);
      entries = data;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      entries = t.split('').map((ch) => ({ char: ch, pinyin: '', tone: 5 }));
    } finally {
      loading = false;
    }
  }

  $: load(text);

  function toneClass(tone: number): string {
    return `tone-${tone}`;
  }
</script>

<span class="hanzi" data-testid={testid}>
  {#if loading}
    <span class="hanzi-loading" aria-busy="true">{text}</span>
  {:else}
    <!-- ponytail: index-based key is fine here because entries are recomputed
         wholesale on every `text` change; if we ever need to swap individual
         entries in/out, switch to a synthetic key like `${i}-${entry.char}`. -->
    {#each entries as entry, i (i)}
      {#if entry.pinyin}
        <span
          class="hanzi-char"
          class:tone-1={entry.tone === 1}
          class:tone-2={entry.tone === 2}
          class:tone-3={entry.tone === 3}
          class:tone-4={entry.tone === 4}
          class:tone-5={entry.tone === 5}
          title={entry.pinyin}
          data-testid="{testid}-char-{entry.char}"
          data-tone={entry.tone}
          data-pinyin={entry.pinyin}
        >{entry.char}</span>
      {:else}
        <span class="hanzi-char plain" data-testid="{testid}-char-{entry.char}">{entry.char}</span>
      {/if}
    {/each}
    {#if error}
      <span class="hanzi-error" role="alert" data-testid="{testid}-error">{error}</span>
    {/if}
  {/if}
</span>

<style>
  .hanzi {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: baseline;
  }

  .hanzi-char {
    display: inline-block;
    padding: 0 1px;
    border-bottom: 3px solid transparent;
    cursor: help;
    transition: background-color 100ms ease;
  }

  .hanzi-char:hover,
  .hanzi-char:focus-visible {
    background-color: rgba(37, 99, 235, 0.08);
    border-radius: 2px;
  }

  .hanzi-char.plain {
    border-bottom: 0;
    cursor: default;
  }

  .hanzi-char.tone-1 {
    border-bottom-color: #dc2626;
  }

  .hanzi-char.tone-2 {
    border-bottom-color: #ea580c;
  }

  .hanzi-char.tone-3 {
    border-bottom-color: #16a34a;
  }

  .hanzi-char.tone-4 {
    border-bottom-color: #2563eb;
  }

  .hanzi-char.tone-5 {
    border-bottom-color: #9ca3af;
  }

  .hanzi-loading,
  .hanzi-error {
    color: var(--lb-muted);
    font-size: 0.95em;
  }

  .hanzi-error {
    color: #b91c1c;
  }
</style>
