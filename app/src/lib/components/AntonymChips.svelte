<script lang="ts">
  /**
   * Chip-style editor for the `antonyms` field on the add-sentence page
   * (Note 3 / T2).
   *
   * User-facing form is **hanzi characters** (e.g. `饱`, `热`).
   * Internally the values flow through to the backend unchanged; the
   * backend (`api/services/antonym_resolver.py`) maps each entry to a
   * word-unit id (pinyin) when wiring the opposite edge.
   *
   * The user can add an antonym by typing hanzi + Enter / comma, and
   * remove one by clicking the `×` button on its chip. Existing
   * chips render above an always-visible input.
   *
   * Props:
   *   - `value`     : bindable list of current antonym strings (hanzi).
   *   - `testid`    : data-testid prefix on the root + chips for tests.
   *   - `placeholder`: input placeholder text.
   */
  export let value: string[] = [];
  export let testid: string = 'antonyms';
  export let placeholder: string = '饱, 热, 冷…';

  let draft = '';

  function addChip(raw: string) {
    const trimmed = raw.trim();
    if (!trimmed) return;
    if (value.includes(trimmed)) {
      draft = '';
      return;
    }
    value = [...value, trimmed];
    draft = '';
  }

  function removeChip(chip: string) {
    value = value.filter((c) => c !== chip);
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addChip(draft);
    } else if (e.key === 'Backspace' && draft === '' && value.length > 0) {
      // Backspace on empty input → remove the last chip.
      value = value.slice(0, -1);
    }
  }

  function onBlur() {
    if (draft.trim()) addChip(draft);
  }
</script>

<div class="chips" data-testid="{testid}-editor">
  {#each value as chip (chip)}
    <span class="chip" data-testid="{testid}-chip-{chip}">
      <span class="chip-text">{chip}</span>
      <button
        type="button"
        class="chip-remove"
        aria-label="Remove {chip}"
        on:click={() => removeChip(chip)}
      >×</button>
    </span>
  {/each}
  <input
    class="chip-input"
    type="text"
    bind:value={draft}
    on:keydown={onKey}
    on:blur={onBlur}
    {placeholder}
    data-testid="{testid}-input"
  />
</div>

<style>
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    padding: 6px 8px;
    border: 1px solid var(--lb-border);
    border-radius: 8px;
    background: var(--lb-bg);
    min-height: 40px;
  }

  .chips:focus-within {
    border-color: var(--lb-accent);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 6px 4px 10px;
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 999px;
    font-size: 14px;
    color: #1e3a8a;
  }

  .chip-text {
    font-weight: 500;
  }

  .chip-remove {
    background: none;
    border: 0;
    padding: 0 4px;
    font-size: 16px;
    line-height: 1;
    color: #6b7280;
    cursor: pointer;
    border-radius: 999px;
  }

  .chip-remove:hover,
  .chip-remove:focus-visible {
    color: #b91c1c;
    background: #fee2e2;
  }

  .chip-input {
    flex: 1;
    min-width: 120px;
    border: 0;
    outline: 0;
    font: inherit;
    font-size: 14px;
    padding: 4px 4px;
    background: transparent;
    color: var(--lb-fg);
  }
</style>
