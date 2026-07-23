#!/bin/bash
# ops/deploy.sh — Deploy language-brain container with AI key
#
# Usage:
#   cp ops/deploy.sh.env.example ops/deploy.sh
#   # edit ops/deploy.sh and set LANGUAGE_BRAIN_AI_KEY=...
#   ops/deploy.sh --dry-run   # echo the docker command without running
#   ops/deploy.sh             # run for real
#
# Required env vars (set in ops/deploy.sh or shell):
#   LANGUAGE_BRAIN_AI_KEY     API key for MiniMax AI

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_SH="$SCRIPT_DIR/deploy.sh"

# Load deploy.sh vars if it exists (and is not this script itself)
if [[ -f "$DEPLOY_SH" ]] && [[ "$DEPLOY_SH" != "$0" ]]; then
  # ponytail: sourced for side-effects only; no exit on error
  set +e
  source "$DEPLOY_SH"
  set -e
fi

# Also allow env var to override file
KEY="${LANGUAGE_BRAIN_AI_KEY:-}"

if [[ -z "$KEY" ]]; then
  echo "ERROR: LANGUAGE_BRAIN_AI_KEY is not set." >&2
  echo "Set it in ops/deploy.sh or export LANGUAGE_BRAIN_AI_KEY='...'" >&2
  exit 1
fi

HOST="192.168.100.101"
IMAGE="language-brain:latest"

DOCKER_CMD="docker run -d \\
  --name language-brain \\
  --restart unless-stopped \\
  -p 8000:8000 \\
  -e LANGUAGE_BRAIN_AI_KEY='$KEY' \\
  -e LANGUAGE_BRAIN_AI_ENDPOINT='https://opencode.ai/zen/go/v1' \\
  -e LANGUAGE_BRAIN_AI_MODEL='deepseek-v4-flash' \\
  -e LANGUAGE_BRAIN_VAULT='/app/vault' \\
  -v /opt/language-brain/vault:/app/vault \\
  -v /opt/language-brain/app/build:/app/static \\
  -v /opt/language-brain/hf-cache:/root/.cache/huggingface \\
  $IMAGE"

if [[ "${1:-}" == "--dry-run" ]]; then
  echo "=== Dry run — inspect the command below before running ==="
  echo "$DOCKER_CMD"
  exit 0
fi

echo "=== Stopping existing container ==="
ssh root@"$HOST" 'docker stop language-brain && docker rm language-brain' 2>/dev/null || true

echo "=== Launching container ==="
ssh root@"$HOST" "$DOCKER_CMD"

echo "=== Waiting for container to start ==="
sleep 4

echo "=== Verifying ==="
ssh root@"$HOST" 'docker ps --filter name=language-brain --format "{{.Names}}\t{{.Status}}"'
RESULT=$(curl -s http://"$HOST":8000/healthz)
echo "$RESULT"
if echo "$RESULT" | grep -q '"mock_mode":false'; then
  echo "=== SUCCESS: mock_mode=false, AI key is active ==="
else
  echo "=== WARNING: mock_mode may still be true — check container env ===" >&2
fi
