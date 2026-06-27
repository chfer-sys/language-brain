// Vitest setup file. Intentionally minimal — Svelte 5 + Vitest works
// out of the box when using the raw `mount` API from 'svelte'.
// (We avoid @testing-library/svelte because its Svelte 5 + Vitest
// condition-resolution path is unstable as of mid-2026 and is not
// needed for the structural assertions in our component tests.)