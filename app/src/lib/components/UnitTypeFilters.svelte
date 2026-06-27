<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { UnitType } from '$lib/api';

  // The three unit-type filters per SPEC §3.2 step 6. Each is on by
  // default. Toggling re-issues the search (parent owns the search
  // call) — no page reload, no router navigation.

  export let enabled: Record<UnitType, boolean> = {
    sentence: true,
    word: true,
    group: true
  };

  const ORDER: UnitType[] = ['sentence', 'word', 'group'];
  const SHORT_LABELS: Record<UnitType, string> = {
    sentence: 'sent',
    word: 'words',
    group: 'groups'
  };

  const dispatch = createEventDispatcher<{ change: Record<UnitType, boolean> }>();

  function toggle(type: UnitType) {
    enabled = { ...enabled, [type]: !enabled[type] };
    dispatch('change', enabled);
  }
</script>

<div class="filters" role="group" aria-label="Unit-type filters" data-testid="type-filters">
  <span class="label">type</span>
  {#each ORDER as type (type)}
    <button
      type="button"
      class="filter"
      class:on={enabled[type]}
      data-type={type}
      aria-pressed={enabled[type]}
      on:click={() => toggle(type)}
    >
      {SHORT_LABELS[type]}
    </button>
  {/each}
</div>

<style>
  .filters {
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

  .filter {
    font: inherit;
    font-size: 12px;
    font-weight: 500;
    padding: 4px 10px;
    border: 1px solid var(--lb-border);
    border-radius: 999px;
    background: var(--lb-bg);
    color: var(--lb-muted);
    cursor: pointer;
    transition: background 100ms ease, color 100ms ease, border-color 100ms ease;
  }

  .filter:hover {
    border-color: #cbd5e1;
  }

  .filter.on {
    background: #1f2937;
    color: white;
    border-color: #1f2937;
  }

  .filter:focus-visible {
    outline: 2px solid var(--lb-accent);
    outline-offset: 2px;
  }
</style>