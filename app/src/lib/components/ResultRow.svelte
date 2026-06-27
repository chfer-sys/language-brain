<script lang="ts">
  import type { SearchResult } from '$lib/api';

  export let result: SearchResult;
</script>

<div>
  {result.name} <small>{result.type}</small>
</div>
