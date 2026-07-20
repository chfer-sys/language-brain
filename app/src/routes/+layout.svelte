<script lang="ts">
  import '../app.css';
  import { getVersion, type VersionInfo } from '$lib/api';

  let versionInfo: VersionInfo | null = null;

  // Fetch version info on mount. Silently fails — badge just stays invisible.
  getVersion().then((v) => { versionInfo = v; }).catch(() => {});
</script>

<slot />

{#if versionInfo}
  <!-- ponytail: debug aid — can be hidden in prod via CSS or env var if desired. -->
  <aside class="version-badge" data-testid="version-badge" aria-label="App version">
    v{versionInfo.version} · {versionInfo.git_commit} · {versionInfo.git_branch}
  </aside>
{/if}

<style>
  .version-badge {
    position: fixed;
    bottom: 8px;
    right: 8px;
    font-size: 11px;
    color: var(--lb-muted, #6b7280);
    background: var(--lb-bg, #fff);
    padding: 3px 7px;
    border-radius: 4px;
    border: 1px solid var(--lb-border, #e5e7eb);
    z-index: 1;
    pointer-events: none;
    user-select: none;
  }
</style>
