<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { ConnectionKind } from '$lib/api';

  // The four kind-toggles per SPEC §3.2 step 5. Each is on by default.
  // Toggling re-issues the search (parent owns the search call) — no
  // page reload, no router navigation.

  export let enabled: Record<ConnectionKind, boolean> = {
    lexical: true,
    semantic: true,
    group: true,
    opposite: true
  };

  const ORDER: ConnectionKind[] = ['lexical', 'semantic', 'group', 'opposite'];
  const SHORT_LABELS: Record<ConnectionKind, string> = {
    lexical: 'lex',
    semantic: 'sem',
    group: 'grp',
    opposite: 'opp'
  };

  const dispatch = createEventDispatcher<{ change: Record<ConnectionKind, boolean> }>();

  function toggle(kind: ConnectionKind) {
    enabled = { ...enabled, [kind]: !enabled[kind] };
    dispatch('change', enabled);
  }
</script>

<div class="toggles" role="group" aria-label="Connection-kind filters" data-testid="kind-toggles">
  <span class="label">kind</span>
  {#each ORDER as kind (kind)}
    <button
      type="button"
      class="toggle"
      class:on={enabled[kind]}
      data-kind={kind}
      aria-pressed={enabled[kind]}
      on:click={() => toggle(kind)}
    >
      {SHORT_LABELS[kind]}
    </button>
  {/each}
</div>

<style>
  .toggles {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .label {
    font-size: 12px;
    color: var(--lb-muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-right: 4px;
  }

  .toggle {
    font: inherit;
    font-size: 12px;
    font-weight: 500;
    text-transform: lowercase;
    padding: 4px 10px;
    border: 1px solid var(--lb-border);
    border-radius: 999px;
    background: var(--lb-bg);
    color: var(--lb-muted);
    cursor: pointer;
    transition: background 100ms ease, color 100ms ease, border-color 100ms ease;
  }

  .toggle:hover {
    border-color: #cbd5e1;
  }

  .toggle.on {
    background: var(--lb-accent);
    color: white;
    border-color: var(--lb-accent);
  }

  .toggle:focus-visible {
    outline: 2px solid var(--lb-accent);
    outline-offset: 2px;
  }
</style>