#!/usr/bin/env bash
# Pre-commit secret guard for language-brain.
#
# Exits non-zero if any tracked file contains:
#   * the literal `LANGUAGE_BRAIN_AI_KEY=` assignment (not in a comment)
#   * a `sk-` style token (heuristic: sk- followed by 16+ alnum chars)
#   * a `M2.7` model token that looks like a leaked key
#         (M2.7 followed by 8+ alnum chars)
#
# Run manually with:  bash scripts/check_no_secrets.sh
# Or install as a git pre-commit hook:
#     ln -s ../../scripts/check_no_secrets.sh .git/hooks/pre-commit
#
# Portable: works with bash 3.2 (macOS default) and newer. Avoids
# `mapfile` (bash 4+) and uses while-read loops instead.

set -euo pipefail

# Files to scan. `git ls-files` lists tracked files; falls back to "."
# when not in a git repo. We populate a temp newline-delimited file
# rather than a bash array, then iterate with `while read`.
FILES_LIST=$(mktemp)
trap 'rm -f "$FILES_LIST" /tmp/check_no_secrets.out /tmp/check_no_secrets.filtered' EXIT

if git rev-parse --git-dir >/dev/null 2>&1; then
  git ls-files > "$FILES_LIST"
else
  find . -type f -not -path './.git/*' > "$FILES_LIST"
fi

file_count=$(wc -l < "$FILES_LIST" | tr -d ' ')
if [ "$file_count" -eq 0 ]; then
  echo "check_no_secrets: no files to scan"
  exit 0
fi

violations=0

scan() {
  local pattern="$1"
  local label="$2"
  # `grep -E` with -nI; ignore binary, print matches with filenames.
  # Use xargs to avoid "argument list too long" on huge trees.
  if xargs -a "$FILES_LIST" grep -nE --binary-files=without-match "$pattern" \
      >/tmp/check_no_secrets.out 2>/dev/null; then
    # Filter out comment-only lines. A "comment" line is one whose
    # first non-whitespace character is `#` (Python/Shell/Markdown/YAML)
    # or `//` (C-family). Docstring lines that mention the env var
    # name as a policy reference are NOT a leak and should not
    # trigger the guard.
    if grep -vE '^[^:]+:[0-9]+:[ \t]*(#|//)' /tmp/check_no_secrets.out \
        >/tmp/check_no_secrets.filtered 2>/dev/null \
        && [ -s /tmp/check_no_secrets.filtered ]; then
      echo "check_no_secrets: $label match(es) found:"
      cat /tmp/check_no_secrets.filtered
      violations=$((violations + 1))
    fi
  fi
}

# Skip the guard script itself (it intentionally references these tokens).
FILTERED_LIST=$(mktemp)
trap 'rm -f "$FILES_LIST" "$FILTERED_LIST" /tmp/check_no_secrets.out /tmp/check_no_secrets.filtered' EXIT
grep -vE '^scripts/check_no_secrets\.sh$' "$FILES_LIST" > "$FILTERED_LIST" || true

# Point the scan function at the filtered list. (We rename the var
# the scan function reads by re-sourcing this section's variable.)
FILES_LIST="$FILTERED_LIST"

filter_count=$(wc -l < "$FILES_LIST" | tr -d ' ')
if [ "$filter_count" -eq 0 ]; then
  echo "check_no_secrets: no scannable files"
  exit 0
fi

scan 'LANGUAGE_BRAIN_AI_KEY=[A-Za-z0-9._-]+'        'LANGUAGE_BRAIN_AI_KEY assignment'
scan 'sk-[A-Za-z0-9]{16,}'                            'sk- style token'
scan 'M2\.7[A-Za-z0-9]{8,}'                           'M2.7 followed by alnum token'

if [ "$violations" -gt 0 ]; then
  echo
  echo "check_no_secrets: FAILED ($violations pattern(s) matched). Aborting commit."
  exit 1
fi

echo "check_no_secrets: clean"
exit 0
