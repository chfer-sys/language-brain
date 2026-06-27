<script lang="ts">
  import SearchBox from '$lib/components/SearchBox.svelte';
  import ResultRow from '$lib/components/ResultRow.svelte';
  import { search, type SearchResult } from '$lib/api';

  const PLACEHOLDER = 'Try: 看起来好吃 or 吃 or basic-verbs';
  const DEBOUNCE_MS = 200;

  let query = '';
  let results: SearchResult[] = [];
  let loading = false;
  let error: string | null = null;
  let requestSeq = 0;

  // AC23: debounce the search by 200ms after the user stops typing.
  // Each input event resets the timer. Only the most recent value
  // triggers a fetch, and stale responses (older requestSeq) are
  // discarded so a slow earlier response can't overwrite a fast
  // later one.
  let timer: ReturnType<typeof setTimeout> | null = null;

  function onInput(e: CustomEvent<string>) {
    query = e.detail;
    if (timer !== null) clearTimeout(timer);
    if (query.trim().length === 0) {
      results = [];
      loading = false;
      error = null;
      return;
    }
    timer = setTimeout(runSearch, DEBOUNCE_MS);
  }

  async function runSearch() {
    const mySeq = ++requestSeq;
    loading = true;
    error = null;
    try {
      const resp = await search(query.trim());
      // Drop stale responses (a newer keystroke already fired).
      if (mySeq !== requestSeq) return;
      results = resp.results;
    } catch (e) {
      if (mySeq !== requestSeq) return;
      error = e instanceof Error ? e.message : String(e);
      results = [];
    } finally {
      if (mySeq === requestSeq) loading = false;
    }
  }
</script>

<svelte:head>
  <title>Language Brain · 语言大脑</title>
</svelte:head>

<div class="hero">
  <header class="brand">
    <h1 class="wordmark">Language Brain</h1>
    <p class="submark" lang="zh">语言大脑</p>
  </header>

  <div class="search-row">
    <SearchBox placeholder={PLACEHOLDER} value={query} on:input={onInput} />
  </div>

  <nav class="add-link-row" aria-label="Primary">
    <a class="add-link" href="/add">+ Add sentence</a>
  </nav>
</div>

<!-- Results pane (below the fold per AC22). Empty state is silent —
     the user only sees results once they type something. -->
<section class="results-pane" aria-label="Search results">
  {#if loading}
    <p class="status">Searching…</p>
  {:else if error}
    <p class="status error" role="alert">{error}</p>
  {:else if query.trim().length > 0 && results.length === 0}
    <p class="status">No results for "{query.trim()}".</p>
  {:else if results.length > 0}
    <ol class="results" data-testid="results">
      {#each results as r (r.id)}
        <li><ResultRow result={r} /></li>
      {/each}
    </ol>
  {/if}
</section>

<style>
  .hero {
    max-width: 720px;
    margin: 0 auto;
    padding: 14vh 24px 24px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 28px;
  }

  .brand {
    text-align: center;
    margin: 0;
  }

  .wordmark {
    font-size: clamp(28px, 4vw, 40px);
    font-weight: 600;
    letter-spacing: -0.01em;
    margin: 0;
    line-height: 1.1;
    color: var(--lb-fg);
  }

  .submark {
    font-size: clamp(14px, 1.6vw, 18px);
    margin: 6px 0 0;
    color: var(--lb-muted);
    letter-spacing: 0.02em;
  }

  .search-row {
    width: 100%;
    max-width: 640px;
  }

  .search-row :global(input[type='search']) {
    width: 100%;
    font: inherit;
    font-size: 18px;
    padding: 14px 18px;
    border: 1px solid var(--lb-border);
    border-radius: 10px;
    background: var(--lb-bg);
    color: var(--lb-fg);
    outline: none;
    transition: border-color 120ms ease, box-shadow 120ms ease;
  }

  .search-row :global(input[type='search']:focus) {
    border-color: var(--lb-accent);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
  }

  .search-row :global(input[type='search']::placeholder) {
    color: var(--lb-muted);
  }

  .add-link-row {
    width: 100%;
    text-align: center;
  }

  .add-link {
    font-size: 15px;
    color: var(--lb-accent);
    text-decoration: none;
    padding: 6px 10px;
    border-radius: 6px;
  }

  .add-link:hover,
  .add-link:focus-visible {
    text-decoration: underline;
  }

  .results-pane {
    max-width: 720px;
    margin: 32px auto 64px;
    padding: 0 24px;
  }

  .status {
    color: var(--lb-muted);
    font-size: 14px;
    text-align: center;
    margin: 0;
    padding: 16px 0;
  }

  .status.error {
    color: #b91c1c;
  }

  .results {
    list-style: none;
    margin: 0;
    padding: 0;
    border-top: 1px solid var(--lb-border);
  }
</style>