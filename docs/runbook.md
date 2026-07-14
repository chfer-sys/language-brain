# language-brain operational runbook

> Last verified: 2026-07-14 (live deploy smoke passed — PASS 2/0)

## 1. Topology

```
┌─────────────────────────────────────────────────────────────────┐
│  This Mac (dev)                                                 │
│  vite dev :5173  →  API http://localhost:8000                  │
│  SPA built to app/build/ (not served locally in prod)          │
└─────────────────────────────────────────────────────────────────┘

                         rsync app/build/

┌─────────────────────────────────────────────────────────────────┐
│  192.168.100.101  (hostname: n8n)                                │
│  docker container: language-brain:latest                        │
│  port: 8000 (uvicorn, SPAStaticFiles)                           │
│  bind mounts:                                                   │
│    /opt/language-brain/vault → /app/vault      (data + dumps)   │
│    /opt/language-brain/app/build → /app/static (SPA bundle)     │
│    /opt/language-brain/hf-cache → /root/.cache/huggingface      │
└─────────────────────────────────────────────────────────────────┘
```

Users browse: **http://192.168.100.101:8000/** (not 127.0.0.1)

Other SSH-known hosts (from `~/.ssh/config`):
- `hermes` (192.168.100.105) — currently unreachable from this Mac
- `pve111` (192.168.1.111) — different subnet

## 2. Build and deploy the SPA bundle

Common path — no container restart needed:

```bash
cd app && npm run build
rsync -avz --delete app/build/ root@192.168.100.101:/opt/language-brain/app/build/
```

Verify:
```bash
diff <(curl -s http://192.168.100.101:8000/_app/version.json) \
     app/build/_app/version.json && echo "version.json matches"
```

FastAPI's `SPAStaticFiles` reads from disk on every request — changes are live immediately. Old browser tabs with stale chunk hashes may need a hard refresh (Ctrl+Shift+R) due to heuristic caching.

## 3. Backend code changes

The `/app/api/` directory is NOT in a bind mount — it lives in the container's image layer.

```bash
docker cp api/<src>.py language-brain:/app/<dest>.py
docker restart language-brain
```

The container has `--restart=unless-stopped`, so it auto-resumes after restart.

For permanent changes: open a PR → CI rebuilds the image → redeploy.

## 4. Model cache

`/root/.cache/huggingface` is bind-mounted from host. Sentence-transformer model (~80 MB) downloads on first run and persists across container restarts and image rebuilds. No re-download needed.

## 5. Gotchas (bugs fixed this session — do not regress)

| Bug | Symptom | Root cause | Fix |
|-----|---------|------------|-----|
| **HanziWithPinyin duplicate-char crash** | "Searching…" forever; `each_key_duplicate` in console | `{#each entries as entry (entry.char)}` — repeated chars in result (e.g. "痒痒", "晚安安") violate Svelte 5 key uniqueness | `{#each entries as entry, i (i)}` (index-keyed) |
| **Frontend fetch had no timeout** | "Searching…" forever on network stall | No `AbortController` + timeout on fetch | `AbortController` with 15_000 ms; keystroke cancels in-flight |
| **SPA bundle had no Cache-Control headers** | Old bundle served to browsers across deploys, masking fixes | `SPAStaticFiles` default — no cache headers | Subclass `SPAStaticFiles` in `api/main.py` to emit `cache-control: no-cache` |
| **`.env` pointed dev at localhost** | Dev mode (5173) hit dead local API | `VITE_API_BASE=http://localhost:8000` | Set to `http://192.168.100.101:8000` |

## 6. Open PRs

| PR | Branch | Description |
|----|--------|-------------|
| [#1](https://github.com/christoferi/language-brain/pull/1) | `hotfix/search-no-results-timeout` | fetch timeout + AbortController |
| [#2](https://github.com/christoferi/language-brain/pull/2) | `hotfix/spa-cache-control-headers` | no-cache on all SPA responses |
| [#3](https://github.com/christoferi/language-brain/pull/3) | `repro/昨晚-query` | repro test for 昨晚 (may be redundant after #4) |
| [#4](https://github.com/christoferi/language-brain/pull/4) | `fix/hanzi-pinyin-duplicate-key` | index-keyed each block in HanziWithPinyin |

Each ships as its own branch off `main`; merge after review.

## 7. Verify a deploy is live

```bash
# version.json matches local build
diff <(curl -s http://192.168.100.101:8000/_app/version.json) \
     app/build/_app/version.json

# cache-control header is present
curl -sI http://192.168.100.101:8000/ | grep cache-control

# Playwright smoke (requires app/tests/_smoke-live.spec.ts)
cd app && npx playwright test _smoke-live.spec.ts --reporter=line
```

Smoke checks `吃` (control) and `昨晚` (regression for #4) — both must resolve within 5 s, no `each_key_duplicate` pageerror, no console errors.

## 8. Quick reference commands

```bash
# Container status
ssh root@192.168.100.101 'docker ps --filter name=language-brain'

# Container logs (last 20 lines)
ssh root@192.168.100.101 'docker logs --since 30m language-brain 2>&1 | tail -20'

# Restart container (after backend hot-patch)
ssh root@192.168.100.101 'docker restart language-brain'

# Check HF cache
ssh root@192.168.100.101 'ls /opt/language-brain/hf-cache/'
```

## 9. Live AI config

The AI key is **NOT** baked into the image. The container runs in `MockAIClient` mode (silent, `mock_mode: true` in `/healthz`) unless the key is supplied at launch.

To set or update the key on a live container:

```bash
# 1. Edit ops/deploy.sh — set LANGUAGE_BRAIN_AI_KEY there.
#    (ops/deploy.sh is gitignored; never commit a real key.)
# 2. Deploy:
ops/deploy.sh          # real run
ops/deploy.sh --dry-run  # inspect the command first
```

`ops/deploy.sh` handles `stop → rm → run` with all bind mounts preserved.

Without the deploy script, the one-liner is:

```bash
KEY='...'  # set in shell, never echo it
ssh root@192.168.100.101 "docker run -d --name language-brain --restart unless-stopped \
  -p 8000:8000 \
  -e LANGUAGE_BRAIN_AI_KEY='$KEY' \
  -e LANGUAGE_BRAIN_AI_ENDPOINT='https://api.minimax.io/v1' \
  -e LANGUAGE_BRAIN_AI_MODEL='MiniMax-M2.1' \
  -e LANGUAGE_BRAIN_VAULT='/app/vault' \
  -v /opt/language-brain/vault:/app/vault \
  -v /opt/language-brain/app/build:/app/static \
  -v /opt/language-brain/hf-cache:/root/.cache/huggingface \
  language-brain:latest"
```

Verify after deploy:

```bash
# Should show mock_mode: false
curl -s http://192.168.100.101:8000/healthz

# Real AI pinyin + meaning (not mock) — takes ~10-15 s
time curl -sX POST http://192.168.100.101:8000/api/sentences \
  -H 'content-type: application/json' \
  -d '{"hanzi":"我喜欢吃","note":""}'
```
