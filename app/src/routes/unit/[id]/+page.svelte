<script lang="ts">
  import { page } from '$app/state';
  import { getUnit, type UnitDetail, type ConnectionKind } from '$lib/api';
  import HanziWithPinyin from '$lib/components/HanziWithPinyin.svelte';

  let unit: UnitDetail | null = null;
  let loading = true;
  let error: string | null = null;
  let lastLoadedId: string | null = null;

  // SvelteKit 2: dynamic route params live on `page.params` from
  // $app/state. Reactive — navigating between unit pages re-runs
  // this block without remounting the component.
  $: routeId = page.params.id;
  $: if (routeId && routeId !== lastLoadedId) {
    lastLoadedId = routeId;
    load(routeId);
  }

  async function load(unitId: string) {
    loading = true;
    error = null;
    unit = null;
    try {
      unit = await getUnit(unitId);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  const KIND_LABELS: Record<ConnectionKind, string> = {
    lexical: 'lexical',
    semantic: 'semantic',
    group: 'group',
    opposite: 'opposite'
  };

  const KIND_ORDER: ConnectionKind[] = ['lexical', 'semantic', 'group', 'opposite'];

  $: connectionsByKind = (() => {
    if (!unit) return {} as Record<ConnectionKind, UnitDetail['connections']>;
    const out: Record<ConnectionKind, UnitDetail['connections']> = {
      lexical: [],
      semantic: [],
      group: [],
      opposite: []
    };
    for (const c of unit.connections) {
      if (c.kind in out) out[c.kind].push(c);
    }
    return out;
  })();

  function topProps(u: UnitDetail): { key: string; value: unknown; renderAs?: 'chips' | 'csv' }[] {
    const p = u.properties;
    const known: { key: string; renderAs?: 'chips' | 'csv' }[] = [];
    if (u.type === 'sentence') {
      known.push(
        { key: 'hanzi' },
        { key: 'pinyin' },
        { key: 'english' },
        { key: 'meaning' },
        { key: 'words', renderAs: 'csv' },
        { key: 'word_refs', renderAs: 'csv' },
        { key: 'groups', renderAs: 'csv' },
        // Antonyms are bare hanzi characters per Note 3 / T2; render
        // them as chips for visual scanability.
        { key: 'antonyms', renderAs: 'chips' }
      );
    } else if (u.type === 'word') {
      known.push(
        { key: 'hanzi' },
        { key: 'pinyin' },
        { key: 'english' },
        { key: 'meaning' },
        { key: 'groups', renderAs: 'csv' },
        { key: 'antonyms', renderAs: 'chips' }
      );
    } else if (u.type === 'group') {
      known.push(
        { key: 'display_name' },
        { key: 'description' },
        { key: 'members', renderAs: 'csv' }
      );
    }
    return known
      .filter((k) => k.key in p)
      .map((k) => ({
        key: k.key,
        renderAs: k.renderAs,
        value: (p as Record<string, unknown>)[k.key]
      }));
  }

  function formatValue(v: unknown): string {
    if (Array.isArray(v)) return v.join(', ');
    if (v === null || v === undefined) return '';
    if (typeof v === 'string') return v;
    return JSON.stringify(v);
  }
</script>

<svelte:head>
  <title>{unit?.name ?? routeId} · Language Brain</title>
</svelte:head>

<main class="page">
  <a class="back" href="/">← Back to search</a>

  {#if loading}
    <p class="status">Loading {routeId}…</p>
  {:else if error}
    <p class="status error" role="alert">{error}</p>
  {:else if unit}
    <header class="header">
      <h1 data-testid="unit-name">
        {#if unit.type === 'sentence' || unit.type === 'word'}
          <HanziWithPinyin text={unit.name} testid="unit-name" />
        {:else}
          {unit.name}
        {/if}
      </h1>
      <span class="type-badge" data-testid="unit-type">{unit.type}</span>
    </header>

    <section class="properties" data-testid="unit-properties">
      <h2>Properties</h2>
      <dl>
        {#each topProps(unit) as { key, value, renderAs } (key)}
          <dt>{key}</dt>
          <dd>
            {#if renderAs === 'chips' && Array.isArray(value)}
              <span class="chips-readonly">
                {#each value as chip (chip)}
                  <span class="chip-readonly" data-testid="prop-antonym-chip-{chip}">{chip}</span>
                {/each}
              </span>
            {:else}
              {formatValue(value)}
            {/if}
          </dd>
        {/each}
      </dl>
    </section>

    <section class="connections" data-testid="unit-connections">
      <h2>Connections</h2>
      {#if unit.connections.length === 0}
        <p class="empty">No outgoing connections yet.</p>
      {:else}
        {#each KIND_ORDER as kind (kind)}
          {#if connectionsByKind[kind].length > 0}
            <div class="kind-group" data-testid="connections-kind-{kind}">
              <h3>{KIND_LABELS[kind]} <span class="count">({connectionsByKind[kind].length})</span></h3>
              <ul>
                {#each connectionsByKind[kind] as c (c.to)}
                  <li>
                    <a href="/unit/{encodeURIComponent(c.to)}">{c.to}</a>
                    <span class="score">{c.score.toFixed(2)}</span>
                  </li>
                {/each}
              </ul>
            </div>
          {/if}
        {/each}
      {/if}
    </section>

    {#if unit.type === 'word' && unit.containing_sentences !== undefined}
      <section class="containing" data-testid="containing-sentences">
        <h2>Sentences containing this word <span class="count">({unit.containing_sentences.length})</span></h2>
        {#if unit.containing_sentences.length === 0}
          <p class="empty" data-testid="no-containing">This word is not yet referenced by any saved sentence.</p>
        {:else}
          <ul>
            {#each unit.containing_sentences as sentenceId (sentenceId)}
              <li>
                <a href="/unit/{encodeURIComponent(sentenceId)}">{sentenceId}</a>
              </li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}
  {/if}
</main>

<style>
  .page {
    max-width: 720px;
    margin: 0 auto;
    padding: 24px 24px 64px;
  }

  .back {
    font-size: 13px;
    color: var(--lb-accent);
    text-decoration: none;
    display: inline-block;
    margin-bottom: 16px;
  }

  .back:hover,
  .back:focus-visible {
    text-decoration: underline;
  }

  .header {
    display: flex;
    align-items: baseline;
    gap: 14px;
    margin-bottom: 24px;
    flex-wrap: wrap;
  }

  .header h1 {
    font-size: 32px;
    font-weight: 600;
    margin: 0;
    line-height: 1.2;
    color: var(--lb-fg);
  }

  .type-badge {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 3px 8px;
    border: 1px solid var(--lb-border);
    border-radius: 4px;
    color: var(--lb-muted);
    background: #f8fafc;
  }

  h2 {
    font-size: 16px;
    font-weight: 600;
    margin: 24px 0 10px;
    color: var(--lb-fg);
  }

  h3 {
    font-size: 13px;
    font-weight: 500;
    margin: 16px 0 6px;
    color: var(--lb-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .count {
    color: var(--lb-muted);
    font-weight: 400;
    margin-left: 4px;
  }

  dl {
    margin: 0;
    display: grid;
    grid-template-columns: 140px 1fr;
    row-gap: 6px;
    column-gap: 14px;
    font-size: 14px;
  }

  dt {
    color: var(--lb-muted);
    font-weight: 500;
  }

  dd {
    margin: 0;
    color: var(--lb-fg);
    word-break: break-word;
  }

  .chips-readonly {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .chip-readonly {
    display: inline-block;
    padding: 2px 8px;
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 999px;
    font-size: 13px;
    color: #1e3a8a;
  }

  .connections ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .connections li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    border-bottom: 1px solid var(--lb-border);
    font-size: 14px;
  }

  .connections a {
    color: var(--lb-fg);
    text-decoration: none;
  }

  .connections a:hover,
  .connections a:focus-visible {
    color: var(--lb-accent);
    text-decoration: underline;
  }

  .score {
    font-variant-numeric: tabular-nums;
    color: var(--lb-muted);
    font-size: 13px;
  }

  .status {
    color: var(--lb-muted);
    font-size: 14px;
    text-align: center;
    margin: 32px 0;
  }

  .status.error {
    color: #b91c1c;
  }

  .empty {
    color: var(--lb-muted);
    font-size: 14px;
    margin: 8px 0 0;
  }

  .containing ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .containing li {
    padding: 6px 0;
    border-bottom: 1px solid var(--lb-border);
    font-size: 14px;
  }

  .containing a {
    color: var(--lb-fg);
    text-decoration: none;
  }

  .containing a:hover,
  .containing a:focus-visible {
    color: var(--lb-accent);
    text-decoration: underline;
  }
</style>