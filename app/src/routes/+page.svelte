<script lang="ts">
  import SearchBox from '$lib/components/SearchBox.svelte';

  // T28 (AC22): default page renders a search box above the fold.
  // T29 wires debounced search. T30 wires toggles/filters/results below the fold.

  const PLACEHOLDER = 'Try: 看起来好吃 or 吃 or basic-verbs';
  let query = '';
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
    <SearchBox placeholder={PLACEHOLDER} bind:value={query} />
  </div>

  <nav class="add-link-row" aria-label="Primary">
    <a class="add-link" href="/add">+ Add sentence</a>
  </nav>
</div>

<!-- Below-the-fold placeholders for T29/T30/T31/T32/T33.
     AC22 only requires the search box above the fold; these are
     stubs that live below it so the page is the single source of
     truth for the UI brick. -->
<section class="below-fold" aria-label="Coming in T29–T33">
  <p class="placeholder-note">Results, toggles, filters, and detail views land in T29–T33.</p>
</section>

<style>
  .hero {
    /* Top-anchored bar layout (option B in design-t28.md):
       the search box sits in the upper portion of the viewport,
       with the bilingual wordmark above it and the "+ Add sentence"
       link centered below it. Everything below is below-the-fold. */
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

  .below-fold {
    /* Below-the-fold content lives inside the 720px column,
       pushed down so it does not compete with the hero on a
       standard viewport. */
    max-width: 720px;
    margin: 0 auto;
    padding: 64px 24px 24px;
    border-top: 1px solid var(--lb-border);
    color: var(--lb-muted);
  }

  .placeholder-note {
    margin: 0;
    font-size: 13px;
    text-align: center;
  }
</style>