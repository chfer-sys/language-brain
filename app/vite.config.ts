import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Plain SvelteKit vite config — no test runner.
export default defineConfig({
  plugins: [sveltekit()]
});
