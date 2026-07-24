# Safe Server Deploy (Preserve AI Key)

**Applies to**: language-brain project. Use to deploy to stable server `192.168.100.101` WITHOUT changing the AI key.

**Skill type**: deploy workflow.

---

## Trigger

User asks to "apply" / "deploy" / "push" to the stable server without specifying an AI key. The deploy script `ops/deploy.sh` is designed for first-time deploys where the user provides a fresh key — overriding env clobbers the active key.

If the user explicitly provides a new AI key, `ops/deploy.sh` may be acceptable; check first.

---

## Why

`ops/deploy.sh` re-uses only the env vars it explicitly knows about and requires `LANGUAGE_BRAIN_AI_KEY` in env or sourced. For ongoing deploys that must preserve the existing key, this is the wrong tool.

The `docker inspect` + `docker run --env-from` pattern is safer because it preserves every env var, mount, restart policy, and port binding atomically.

This approach was developed during the v0.8.6 deploy on 2026-07-16. See memory entry `mem_mrni5rae_ba940fecb3ae` for the deployed commit context.

---

## Workflow

### 1. Investigate first (unless done this session)

```bash
ssh -o StrictHostKeyChecking=accept-new root@192.168.100.101 '
echo "=== container ==="
docker ps -a --filter name=language-brain --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
echo "=== image ==="
docker images language-brain --format "table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}"
echo "=== /opt/language-brain ==="
ls -la /opt/language-brain/
du -sh /opt/language-brain/* 2>&1
echo "=== git clone state ==="
cd /opt/language-brain/src 2>/dev/null && git log -1 --format="%H %s" && git status --short || echo "no src clone"
echo "=== current health ==="
curl -s http://127.0.0.1:8000/healthz 2>&1
'
```

Report findings; let the user pick build-on-server vs build-and-transfer.

### 2. Capture existing container's full config

```bash
ssh root@192.168.100.101 '
ENV_ARGS=$(docker inspect language-brain --format "{{range .Config.Env}}{{printf \"-e %s \" .}}{{end}}")
MOUNT_ARGS=$(docker inspect language-brain --format "{{range .Mounts}}{{printf \"-v %s:%s \" .Source .Destination}}{{end}}")
PORT_ARGS=$(docker inspect language-brain --format '{{range $p, $b := .HostConfig.PortBindings}}{{range $b}}{{printf "-p %s:%s " (index (split $p "/") 0) (index . 0).HostPort}}{{end}}{{end}}')
RESTART=$(docker inspect language-brain --format "{{.HostConfig.RestartPolicy.Name}}")
echo "$ENV_ARGS"   > /tmp/lb-env.sh
echo "$MOUNT_ARGS" > /tmp/lb-mounts.sh
echo "$PORT_ARGS"  > /tmp/lb-ports.sh
echo "$RESTART"    > /tmp/lb-restart.txt
'
```

If `PORT_ARGS` ends up empty (template parse error observed once), fall back to hardcoded `-p 8000:8000` in step 5.

### 2.5. Strip quotes from env file (mandatory)

The `%s` template may still produce quoted values if the original env var contained spaces. Strip all literal quotes to prevent parsing errors:

```bash
ssh root@192.168.100.101 'sed -i "s/\"//g" /tmp/lb-env.sh'
```

This is a known gotcha from the v0.9 deploys (2026-07-24). Without this step, the recreated container will have malformed env vars (e.g., `mock_mode:true`).

### 2.6. Selective env override (optional)

If the user wants to change a specific env var while preserving everything else, edit `/tmp/lb-env.sh` on the server:

```bash
ssh root@192.168.100.101 '
# Example: override AI model
sed -i "s/LANGUAGE_BRAIN_AI_MODEL=[^ ]*/LANGUAGE_BRAIN_AI_MODEL=mimo-v2.5/g" /tmp/lb-env.sh
# Verify the change
grep LANGUAGE_BRAIN_AI_MODEL /tmp/lb-env.sh
'
```

This was a critical gotcha in the mimo-v2.5 deploy (2026-07-24): without the override, the recreated container kept the old `deepseek-v4-flash` model.

### 3. Update source on server — STASH FIRST

The server clone at `/opt/language-brain/src` accumulates local modifications across deploys (`.specs/_traces.md` and `vault/.gitkeep` files were stashed on 2026-07-16). Always stash before pulling.

```bash
ssh root@192.168.100.101 '
cd /opt/language-brain/src
# Detect current branch (preserve it — the live server may run a feature branch)
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "Current branch: $CURRENT_BRANCH"
git stash push -u -m "pre-deploy-stash" 2>&1 | tail -3
git fetch origin 2>&1 | tail -3
git checkout "$CURRENT_BRANCH" 2>&1
git pull origin "$CURRENT_BRANCH" 2>&1 | tail -5
git log -1 --format="%H %s"
'
```

If the user explicitly requests a branch switch (e.g., "deploy v0.9 to the server"), override `$CURRENT_BRANCH` with the target branch before the checkout.

Tell the user about any stash created — they may want to inspect later.

### 4. Build image on server (3–5 min CPU-only)

```bash
ssh root@192.168.100.101 '
cd /opt/language-brain/src
time docker build -f Dockerfile -t language-brain:latest . 2>&1 | tail -20
docker images language-brain:latest --format "table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}"
'
```

If build fails, capture the error and STOP. Don't try to fix the Dockerfile without user approval.

### 5. Recreate container with captured env

```bash
ssh root@192.168.100.101 '
set -e
ENV_ARGS=$(cat /tmp/lb-env.sh)
MOUNT_ARGS=$(cat /tmp/lb-mounts.sh)
PORT_ARGS=$(cat /tmp/lb-ports.sh)
RESTART=$(cat /tmp/lb-restart.txt)
# If PORT_ARGS empty (parse error), fall back:
if [[ -z "$PORT_ARGS" ]]; then
  PORT_ARGS="-p 8000:8000"
fi
docker stop language-brain 2>&1
docker rm   language-brain 2>&1
docker run -d \
  --name language-brain \
  --restart "$RESTART" \
  $PORT_ARGS \
  $ENV_ARGS \
  $MOUNT_ARGS \
  language-brain:latest
sleep 4
docker ps --filter name=language-brain --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
echo "=== healthz ==="
curl -s http://127.0.0.1:8000/healthz
'
```

### 6. Verify from this Mac

```bash
curl -s -w "\nHTTP %{http_code}\n" http://192.168.100.101:8000/healthz  # expect 200, mock_mode:false
curl -s http://192.168.100.101:8000/api/units/<unit-that-changed> | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print('field check:', d.get('<new-field>'))"
```

### 7. Stash on server — tell user

```bash
ssh root@192.168.100.101 'cd /opt/language-brain/src && git stash list'
```

Mention to the user; they decide whether to `git stash pop` (which may conflict with v0.8.x changes).

---

## Don't

- Don't run `ops/deploy.sh` directly unless user provided a new AI key.
- Don't override env vars with placeholder values.
- Don't skip the stash step — the server clone has had uncommitted changes twice in this project's history.
- Don't force-push anything — the server is live.
