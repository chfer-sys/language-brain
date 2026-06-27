<script lang="ts">
  import type { SearchResult } from '$lib/api';

  export let result: SearchResult;

  // Human-readable kinds chip labels. Order is stable so the UI is
  // deterministic across renders.
  const KIND_LABELS: Record<string, string> = {
    lexical: 'lex',
    semantic: 'sem',
    group: 'grp',
    opposite: 'opp'
  };

  $: href = result.type === 'group' ? `/group/${result.id}` : `/unit/${result.id}`;
</script>

<a class="row" {href} data-testid="result-row" data-unit-type={result.type}>
  <span class="name">{result.name}</span>
  <span class="snippet">{result.snippet}</span>
  <span class="kinds">
    {#each result.kinds as k (k)}
      <span class="kind" data-kind={k}>{KIND_LABELS[k] ?? k}</span>
    {/each}
  </span>
  <span class="score" aria-label="relevance score">{result.score.toFixed(2)}</span>
</a>

<style>
  .row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr) auto auto;
    gap: 14px;
    align-items: center;
    padding: 10px 14px;
    border-bottom: 1px solid var(--lb-border);
    color: var(--lb-fg);
    text-decoration: none;
    font-size: 15px;
    line-height: 1.4;
  }

  .row:hover,
  .row:focus-visible {
    background: #f8fafc;
  }

  .name {
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .snippet {
    color: var(--lb-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .kinds {
    display: inline-flex;
    gap: 4px;
  }

  .kind {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 2px 6px;
    border: 1px solid var(--lb-border);
    border-radius: 4px;
    color: var(--lb-muted);
    background: var(--lb-bg);
  }

  .score {
    font-variant-numeric: tabular-nums;
    color: var(--lb-muted);
    font-size: 13px;
    min-width: 3ch;
    text-align: right;
  }
</style>