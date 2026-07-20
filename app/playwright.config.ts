import { defineConfig } from '@playwright/test';

// External deployment target (e.g. LAN preview). When set, we skip the
// local Vite dev server — the tests just point at BASE_URL.
//   BASE_URL=http://192.168.100.101:8000 npx playwright test _lan-deployed-v09
const EXTERNAL_BASE_URL = process.env.BASE_URL;

// Chromium only — SPEC: desktop-browser MVP.
export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  use: {
    baseURL: EXTERNAL_BASE_URL ?? 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  // Backend lifecycle (docker start + health wait) is handled in the spec
  // file's test.beforeAll() so it runs in the same Node process and avoids
  // ESM/CJS import issues with globalSetup.
  //
  // Vite dev server is started here with the correct VITE_API_BASE so the
  // frontend talks to the backend on 127.0.0.1:8000 (not the LAN server).
  //
  // When BASE_URL is set we are targeting an external deployment (LAN, preview)
  // and MUST NOT start the local dev server.
  webServer: EXTERNAL_BASE_URL
    ? undefined
    : {
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
