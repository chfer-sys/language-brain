<script lang="ts">
  /**
   * Chip-style editor for the `groups` field on the add-sentence page,
   * with autocomplete from the existing group list.
   *
   * Unlike the bare-hanzi antonym editor, group chips show a human-readable
   * display_name (e.g. "Social Interaction") while the internal value is
   * the group slug id (e.g. "social-interaction").
   *
   * Props:
   *   - `value`          : bindable list of current group slug ids.
   *   - `suggestions`   : list of existing groups for autocomplete.
   *   - `placeholder`   : input placeholder text.
   *   - `testid`        : data-testid prefix on the root + chips for tests.
   */
  export let value: string[] = [];
  export let suggestions: { id: string; display_name: string }[] = [];
  export let placeholder: string = 'Type or select a group…';
  export let testid: string = 'groups';

  let draft = '';
  let showDropdown = false;

  // ponytail: O(n) filter on every keystroke is fine for <1000 groups.
  $: filtered = suggestions.filter(
    (s) =>
      !value.includes(s.id) &&
      (s.id.toLowerCase().includes(draft.toLowerCase()) ||
        s.display_name.toLowerCase().includes(draft.toLowerCase()))
  );

  function displayNameFor(slug: string): string {
    return suggestions.find((s) => s.id === slug)?.display_name ?? slug;
  }

  function addChip(raw: string) {
    const trimmed = raw.trim();
    if (!trimmed) return;
    const slug = trimmed.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');
    if (value.includes(slug)) {
      draft = '';
      showDropdown = false;
      return;
    }
    value = [...value, slug];
    draft = '';
    showDropdown = false;
  }

  function removeChip(slug: string) {
    value = value.filter((c) => c !== slug);
  }

  function selectSuggestion(suggestion: { id: string; display_name: string }) {
    if (value.includes(suggestion.id)) return;
    value = [...value, suggestion.id];
    draft = '';
    showDropdown = false;
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      if (showDropdown && filtered.length > 0) {
        selectSuggestion(filtered[0]);
      } else {
        addChip(draft);
      }
    } else if (e.key === 'Escape') {
      showDropdown = false;
    } else if (e.key === 'Backspace' && draft === '' && value.length > 0) {
      value = value.slice(0, -1);
    }
  }

  function onInput() {
    showDropdown = draft.length > 0;
  }

  function onBlur() {
    showDropdown = false;
    if (draft.trim()) addChip(draft);
  }
</script>

<div class="chips" data-testid="{testid}-editor">
  {#each value as slug (slug)}
    <span class="chip" data-testid="{testid}-chip-{slug}">
      <span class="chip-text">{displayNameFor(slug)}</span>
      <button
        type="button"
        class="chip-remove"
        aria-label="Remove {slug}"
        on:click={() => removeChip(slug)}
      >×</button>
    </span>
  {/each}
  <div class="chip-input-wrap">
    <input
      class="chip-input"
      type="text"
      bind:value={draft}
      on:keydown={onKey}
      on:input={onInput}
      on:blur={onBlur}
      {placeholder}
      data-testid="{testid}-input"
      autocomplete="off"
    />
    {#if showDropdown && filtered.length > 0}
      <ul class="chip-dropdown" data-testid="{testid}-dropdown">
        {#each filtered as s (s.id)}
          <li>
            <button
              type="button"
              class="chip-dropdown-item"
              on:click={() => selectSuggestion(s)}
            >{s.display_name}</button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
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

  .chip-input-wrap {
    position: relative;
    flex: 1;
    min-width: 120px;
  }

  .chip-input {
    width: 100%;
    border: 0;
    outline: 0;
    font: inherit;
    font-size: 14px;
    padding: 4px 4px;
    background: transparent;
    color: var(--lb-fg);
    box-sizing: border-box;
  }

  .chip-dropdown {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    margin: 0;
    padding: 4px 0;
    list-style: none;
    background: var(--lb-bg);
    border: 1px solid var(--lb-border);
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    z-index: 100;
    max-height: 200px;
    overflow-y: auto;
  }

  .chip-dropdown-item {
    display: block;
    width: 100%;
    text-align: left;
    padding: 8px 12px;
    background: none;
    border: 0;
    font: inherit;
    font-size: 14px;
    color: var(--lb-fg);
    cursor: pointer;
  }

  .chip-dropdown-item:hover,
  .chip-dropdown-item:focus-visible {
    background: #eff6ff;
    color: #1e3a8a;
  }
</style>
