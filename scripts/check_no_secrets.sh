#!/usr/bin/env bash
# Pre-commit secret guard for language-brain.
#
# Exits non-zero if any tracked file contains:
#   * the literal `LANGUAGE_BRAIN_AI_KEY=` assignment
#   * a `sk-` style token (heuristic: sk- followed by 16+ alnum chars)
#   * a `M2.7` model token that looks like a leaked key
#         (M2.7 followed by 8+ alnum chars)
#
# Run manually with:  bash scripts/check_no_secrets.sh
# Or install as a git pre-commit hook:
#     ln -s ../../scripts/check_no_secrets.sh .git/hooks/pre-commit

set -euo pipefail

# Files to scan. `git ls-files` lists tracked files; falls back to "."
# when not in a git repo.
if git rev-parse --git-dir >/dev/null 2>&1; then
  mapfile -t FILES < <(git ls-files)
else
  mapfile -t FILES < <(find . -type f -not -path './.git/*')
fi

if [ "${#FILES[@]}" -eq 0 ]; then
  echo "check_no_secrets: no files to scan"
  exit 0
fi

violations=0

scan() {
  local pattern="$1"
  local label="$2"
  # `grep -E` with -nI; ignore binary, print matches with filenames.
  if grep -nE --binary-files=without-match "$pattern" "${FILES[@]}" \
      >/tmp/check_no_secrets.out 2>/dev/null; then
    echo "check_no_secrets: $label match(es) found:"
    cat /tmp/check_no_secrets.out
    violations=$((violations + 1))
  fi
}

# Skip the guard script itself (it intentionally references these tokens).
filtered=()
for f in "${FILES[@]}"; do
  case "$f" in
    scripts/check_no_secrets.sh|.env.example) ;;  # skip — see pattern docs above
    *) filtered+=("$f") ;;
  esac
done
FILES=("${filtered[@]}")

if [ "${#FILES[@]}" -eq 0 ]; then
  echo "check_no_secrets: no scannable files"
  exit 0
fi

scan 'LANGUAGE_BRAIN_AI_KEY=[A-Za-z0-9._-]+'        'LANGUAGE_BRAIN_AI_KEY assignment'
scan 'sk-[A-Za-z0-9]{16,}'                            'sk- style token'
scan 'M2\.7[A-Za-z0-9]{8,}'                           'M2.7 followed by alnum token'

rm -f /tmp/check_no_secrets.out

if [ "$violations" -gt 0 ]; then
  echo
  echo "check_no_secrets: FAILED ($violations pattern(s) matched). Aborting commit."
  exit 1
fi

echo "check_no_secrets: clean"
exit 0
