# Pre-Push Real-Browser Preview

**Applies to**: language-brain project (FastAPI + SvelteKit). Use after merging to main, before pushing to origin or deploying to the stable server.

**Skill type**: workflow.

---

## Trigger

You have just merged changes to local main AND either:
- About to push to origin, OR
- About to deploy to 192.168.100.101.

If neither is true, skip.

---

## Why

The Playwright test suite in `app/tests/` has a pre-existing mock-environment mismatch — it mocks `http://localhost:8000` while Vite dev server uses `127.0.0.1:8000` (set via `VITE_API_BASE`). The regex in `page.route()` doesn't match the real fetch URL, so `page.route()` doesn't intercept and tests fall through to the real backend with no fixture data. Result: 10+ tests fail with this pattern (4/14 in unit-detail.spec.ts, 2/7 in vault_browse.spec.ts).

Unit tests miss URL-param, client-side-nav, and render-state bugs. Real-browser preview against the live dev servers catches what tests cannot.

This skill caught:
- **v0.7.1** — URL query params ignored by `/vault` when navigating with `?type=word`.
- **v0.8.5** — stale-render on `/unit/<id>` (URL changed but page kept rendering the previous unit's data).

---

## Workflow

### 1. Confirm dev servers running

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5173/            # expect 200
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/units/S1  # expect 200
```

If either is down, restart per local-dev convention:

```bash
# API
cd /Users/christoferi/lantern/projects/language-brain
nohup python3 -m uvicorn api.main:app --host 127.0.0.1 --port 8000 > /tmp/api.log 2>&1 &

# Frontend (Vite)
cd /Users/christoferi/lantern/projects/language-brain/app
nohup env VITE_API_BASE=http://127.0.0.1:8000 npm run dev -- --port 5173 > /tmp/web.log 2>&1 &
```

Vite HMR picks up SvelteKit changes automatically. FastAPI does NOT — restart it after backend code changes.

### 2. Write a Playwright script

Save to `app/verify-<feature>.mjs`. Exercise the **user journeys touched by the change**:

For vault-list changes, cover:
- `/`, `/vault`, `/vault?type=word`, `/vault?type=compound`, `/vault?type=word&sort=pinyin`

For unit-page changes, cover:
- Open `/unit/<id>` directly (cold load).
- Click word_refs chips: `[data-testid="prop-word_refs-chip-<id>"]`.
- Click connection links: `[data-testid="unit-connections"] a[href^="/unit/"]`.
- Click back button: `[data-testid="back-link"]`.

For URL/sort changes, cover:
- Cold load with query params (verifies the `onMount`-driven URL sync).
- Click that mutates query params and verify URL updates.

### 3. Assert against UI state, not just network responses

Prefer:
- `await page.locator('[data-testid="unit-properties"] dd').count()` — for sentence/word targets, expect ≥6.
- `await page.title()` — confirms render updated.
- `page.url()` — confirms navigation occurred.

For compound units, the `<dd>` count is 0 (see AGENTS.md rule). Use title + URL change as primary signal.

### 4. Capture screenshots

```js
await page.screenshot({ path: '/tmp/<feature>-previews/<step>.png', fullPage: true });
```

Use `/tmp/` — files are ephemeral, not committed.

### 5. Report

Output: which user journeys PASS, which FAIL, and screenshots saved.
