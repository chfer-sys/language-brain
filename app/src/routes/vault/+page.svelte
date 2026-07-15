<script lang="ts">
  import { vaultList, type VaultBrowseType, type VaultSortKey } from '$lib/api';

  const LIMIT = 50;

  let activeType: VaultBrowseType = 'sentence';
  let sort: VaultSortKey = 'id';
  let offset = 0;
  let total = 0;
  let items: { id: string; name: string; snippet: string }[] = [];
  let loading = false;
  let error: string | null = null;

  // Tab order: Word → Compound → Sentence (matches tab UI spec).
  const TABS: VaultBrowseType[] = ['word', 'compound', 'sentence'];
  const TAB_LABELS: Record<VaultBrowseType, string> = {
    word: 'Word',
    compound: 'Compound',
    sentence: 'Sentence'
  };

  async function load() {
    loading = true;
    error = null;
    try {
      const resp = await vaultList(activeType, { limit: LIMIT, offset, sort });
      total = resp.total;
      items = resp.items;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      items = [];
    } finally {
      loading = false;
    }
  }

  async function selectTab(type: VaultBrowseType) {
    activeType = type;
    offset = 0;
    await load();
  }

  async function changeSort(newSort: VaultSortKey) {
    sort = newSort;
    offset = 0;
    await load();
  }

  async function prev() {
    offset = Math.max(0, offset - LIMIT);
    await load();
  }

  async function next() {
    offset = offset + LIMIT;
    await load();
  }

  $: hasPrev = offset > 0;
  $: hasNext = offset + LIMIT < total;

  // Initial load.
  load();
</script>

<svelte:head>
  <title>Browse vault · Language Brain</title>
</svelte:head>

<main class="page">
  <header class="header">
    <a class="back" href="/">← Back</a>
    <h1>Browse vault</h1>
  </header>

  <div class="controls">
    <div class="tabs" role="tablist" aria-label="Unit type">
      {#each TABS as tab (tab)}
        <button
          type="button"
          role="tab"
          class="tab"
          class:active={activeType === tab}
          aria-selected={activeType === tab}
          data-type={tab}
          on:click={() => selectTab(tab)}
        >
          {TAB_LABELS[tab]}
        </button>
      {/each}
    </div>

    <label class="sort-label">
      sort
      <select
        class="sort-select"
        bind:value={sort}
        on:change={() => changeSort(sort)}
        aria-label="Sort order"
      >
        <option value="id">id</option>
        <option value="pinyin">pinyin</option>
      </select>
    </label>
  </div>

  {#if loading}
    <p class="status">Loading…</p>
  {:else if error}
    <p class="status error" role="alert">{error}</p>
  {:else if items.length === 0}
    <p class="status">No items found.</p>
  {:else}
    <ol class="list" data-testid="vault-list">
      {#each items as item (item.id)}
        <li>
          <a class="row" href="/unit/{item.id}">
            <span class="row-id">{item.id}</span>
            <span class="row-name">{item.name}</span>
            <span class="row-snippet">{item.snippet}</span>
          </a>
        </li>
      {/each}
    </ol>

    {#if total > LIMIT}
      <div class="pagination" data-testid="pagination">
        <button
          type="button"
          class="page-btn"
          disabled={!hasPrev}
          on:click={prev}
          aria-label="Previous page"
        >
          ← Prev
        </button>
        <span class="page-info">
          {offset + 1}–{Math.min(offset + LIMIT, total)} of {total}
        </span>
        <button
          type="button"
          class="page-btn"
          disabled={!hasNext}
          on:click={next}
          aria-label="Next page"
        >
          Next →
        </button>
      </div>
    {/if}
  {/if}
</main>

<style>
  .page {
    max-width: 720px;
    margin: 0 auto;
    padding: 32px 24px 64px;
  }

  .header {
    margin-bottom: 24px;
  }

  .back {
    font-size: 13px;
    color: var(--lb-accent);
    text-decoration: none;
    display: inline-block;
    margin-bottom: 12px;
  }

  .back:hover,
  .back:focus-visible {
    text-decoration: underline;
  }

  .header h1 {
    font-size: 28px;
    font-weight: 600;
    margin: 0;
    color: var(--lb-fg);
  }

  .controls {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }

  .tabs {
    display: inline-flex;
    gap: 4px;
  }

  .tab {
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    padding: 6px 14px;
    border: 1px solid var(--lb-border);
    border-radius: 999px;
    background: var(--lb-bg);
    color: var(--lb-muted);
    cursor: pointer;
    transition: background 100ms ease, color 100ms ease, border-color 100ms ease;
  }

  .tab:hover {
    border-color: #cbd5e1;
  }

  .tab.active {
    background: #1f2937;
    color: white;
    border-color: #1f2937;
  }

  .tab:focus-visible {
    outline: 2px solid var(--lb-accent);
    outline-offset: 2px;
  }

  .sort-label {
    font-size: 12px;
    color: var(--lb-muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .sort-select {
    font: inherit;
    font-size: 12px;
    padding: 4px 8px;
    border: 1px solid var(--lb-border);
    border-radius: 6px;
    background: var(--lb-bg);
    color: var(--lb-fg);
    cursor: pointer;
  }

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    border-top: 1px solid var(--lb-border);
  }

  .row {
    display: grid;
    grid-template-columns: 60px 1fr 1fr;
    gap: 12px;
    padding: 10px 12px;
    border-bottom: 1px solid var(--lb-border);
    text-decoration: none;
    color: var(--lb-fg);
    align-items: center;
    transition: background 80ms ease;
  }

  .row:hover,
  .row:focus-visible {
    background: var(--lb-bg-hover, #f8fafc);
  }

  .row-id {
    font-size: 12px;
    color: var(--lb-muted);
    font-family: ui-monospace, monospace;
  }

  .row-name {
    font-size: 16px;
    font-weight: 500;
  }

  .row-snippet {
    font-size: 14px;
    color: var(--lb-muted);
  }

  .pagination {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    margin-top: 24px;
  }

  .page-btn {
    font: inherit;
    font-size: 13px;
    padding: 6px 14px;
    border: 1px solid var(--lb-border);
    border-radius: 6px;
    background: var(--lb-bg);
    color: var(--lb-fg);
    cursor: pointer;
  }

  .page-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .page-btn:not(:disabled):hover {
    border-color: #cbd5e1;
  }

  .page-info {
    font-size: 13px;
    color: var(--lb-muted);
  }

  .status {
    color: var(--lb-muted);
    font-size: 14px;
    margin: 0;
    padding: 16px 0;
  }

  .status.error {
    color: #b91c1c;
  }
</style>
