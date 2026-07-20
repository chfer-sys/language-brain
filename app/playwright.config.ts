import { defineConfig } from '@playwright/test';

// Chromium only — SPEC: desktop-browser MVP.
export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  // Backend lifecycle (docker start + health wait) is handled in the spec
  // file's test.beforeAll() so it runs in the same Node process and avoids
  // ESM/CJS import issues with globalSetup.
  //
  // Vite dev server is started here with the correct VITE_API_BASE so the
  // frontend talks to the backend on 127.0.0.1:8000 (not the LAN server).
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 120_000,
    env: {
      VITE_API_BASE: 'http://127.0.0.1:8000',
    },
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
});
