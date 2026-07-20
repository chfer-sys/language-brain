/**
 * globalSetup.js — starts the FastAPI backend via docker before any tests run.
 *
 * Backend lifecycle:
 * - Checks if something is already listening on port 8000; if so, skips start.
 * - Otherwise launches `docker run --rm -p 8000:8000 ...` and waits for /healthz.
 *
 * This lets the smoke spec run against an externally-managed backend
 * (e.g. a 24/7 dev server) without requiring docker in every run.
 */

import { execFile } from 'child_process';
import { readFileSync, writeFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import net from 'net';
import http from 'http';

const __dirname = dirname(fileURLToPath(import.meta.url));

const BACKEND_PORT = 8000;
const BACKEND_HEALTH_URL = `http://127.0.0.1:${BACKEND_PORT}/healthz`;
const MAX_WAIT_MS = 60_000;
const POLL_INTERVAL_MS = 500;

function runCommand(cmd, args) {
  return new Promise((resolve, reject) => {
    execFile(cmd, args, (err, stdout, stderr) => {
      if (err) reject(err);
      else resolve((stdout || '') + (stderr || ''));
    });
  });
}

async function isPortListening(port) {
  return new Promise((resolve) => {
    const sock = net.createConnection({ port, host: '127.0.0.1' });
    sock.setTimeout(800);
    sock.on('connect', () => { sock.destroy(); resolve(true); });
    sock.on('timeout', () => { sock.destroy(); resolve(false); });
    sock.on('error', () => resolve(false));
  });
}

async function waitForUrl(url, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await new Promise((resolve, reject) => {
        const req = http.get(url, (res) => resolve(res));
        req.on('error', reject);
        req.setTimeout(POLL_INTERVAL_MS, () => req.destroy());
      });
      res.destroy();
      if (res.statusCode && res.statusCode < 500) return;
    } catch {
      // not ready yet
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  throw new Error(`Timed out waiting for ${url} after ${timeoutMs}ms`);
}

async function globalSetup() {
  // Detect repo root (parent of `app/`)
  const repoRoot = resolve(__dirname, '..');

  // Check if backend is already running
  const alreadyRunning = await isPortListening(BACKEND_PORT);
  if (alreadyRunning) {
    console.log(`[globalSetup] Backend already on ${BACKEND_PORT}, skipping docker start.`);
  } else {
    console.log(`[globalSetup] Starting FastAPI backend via docker on ${BACKEND_PORT}...`);

    // Kill any stale container on this port
    try {
      const existing = await runCommand('docker', [
        'ps', '-q',
        '--filter', `publish=${BACKEND_PORT}`,
        '--format', '{{.ID}}',
      ]);
      if (existing.trim()) {
        console.log('[globalSetup] Killing stale container...');
        await runCommand('docker', ['kill', existing.trim()]);
        await new Promise((r) => setTimeout(r, 1500));
      }
    } catch {
      // docker not available or no containers — continue
    }

    // Start fresh container
    const containerOut = await runCommand('docker', [
      'run',
      '--rm',
      '-d',
      '-p', `${BACKEND_PORT}:${BACKEND_PORT}`,
      '-v', `${repoRoot}:/work`,
      '-w', '/work',
      '-e', `LANGUAGE_BRAIN_VAULT=${repoRoot}/vault`,
      'opencode-language-brain-test',
      'python', '-m', 'uvicorn',
      'api.main:app',
      '--host', '0.0.0.0',
      '--port', String(BACKEND_PORT),
    ]);
    const cid = containerOut.trim().split('\n')[0];
    console.log(`[globalSetup] Backend container: ${cid}`);
    // Store container id so globalTeardown can clean it up
    writeFileSync(resolve(repoRoot, 'app', '.smoke-container-id'), cid);
  }

  // Wait for backend health
  console.log('[globalSetup] Waiting for backend /healthz...');
  await waitForUrl(BACKEND_HEALTH_URL, MAX_WAIT_MS);
  console.log('[globalSetup] Backend is healthy.');
}

const globalTeardown = async () => {};

export { globalSetup, globalTeardown };
