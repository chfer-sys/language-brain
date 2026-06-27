<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  export let placeholder: string;
  export let value: string = '';

  const dispatch = createEventDispatcher<{ input: string }>();

  function onInput(e: Event) {
    const target = e.target as HTMLInputElement;
    value = target.value;
    dispatch('input', value);
  }
</script>

<input
  type="search"
  {placeholder}
  {value}
  on:input={onInput}
/>
