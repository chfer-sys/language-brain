import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

// Vite/Vitest config for the Language Brain SvelteKit frontend.
//
// Note on the `browser` resolve condition: we apply it ONLY when running
// the vitest test pipeline. Without it, vitest resolves the `svelte`
// package to its index-server.js build (which does not export `mount`)
// and every component test crashes with `lifecycle_function_unavailable`.
// The condition is scoped to the test config so it does not corrupt the
// dev/build SSR pipeline — applying it globally makes SvelteKit try to
// load the client runtime on the server (window is undefined).
export default defineConfig(({ mode }) => ({
  plugins: [sveltekit()],
  ...(mode === 'test'
    ? {
        resolve: {
          conditions: ['browser']
        },
        optimizeDeps: {
          esbuildOptions: {
            conditions: ['browser']
          }
        }
      }
    : {}),
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts']
  }
}));
