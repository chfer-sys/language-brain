# Fix-and-Commit Recovery

**Applies to**: language-brain project. Use when a subagent reports `NEEDS-FIX` due to permission denials on bash, but the code IS already in the working tree on an orphan branch.

**Skill type**: recovery workflow.

---

## Trigger

You dispatched an executor or debug subagent to implement a fix. It returned `NEEDS-FIX` with output like:

> "Permission system is blocking all bash commands. Code changes are in working tree but uncommitted on orphan branch X."

This pattern occurred 4+ times during v0.7 → v0.8:
- Phase A executor wrote the diff but didn't commit.
- Phase B executor committed only 2 of 5 files.
- Debug v0.7.1 edited but didn't commit.
- Debug v0.8.5 diagnosed correctly but couldn't run git/merge.

Don't re-diagnose the bug — the previous subagent's diagnosis was almost certainly correct. Re-running the full flow wastes 5–15 minutes.

---

## Workflow

### 1. Inspect orphan branch state

```bash
cd /Users/christoferi/lantern/projects/language-brain
git branch --show-current
git status --short
git diff --stat
git log --oneline -3
```

Identify:
- The intended fix (probably 1–3 files with a clean diff).
- Leftover scratch from prior dispatches: orphan test mock changes, `app/inspect-*.mjs` scripts, `.specs/_traces.md` mods.

### 2. Reset to a clean main state

```bash
git checkout main
git checkout -- app/tests/unit-detail.spec.ts app/tests/vault_browse.spec.ts 2>&1 || true
git checkout -- .specs/_traces.md 2>&1 || true
git clean -fd app/                                                    # remove inspect-*.mjs
git branch -D <orphan-branch-1>                                       # 2>&1 || true
git branch -D <orphan-branch-2>                                       # 2>&1 || true
git status --short
```

Expected final output:

```
?? .specs/versions/docs-rewrite-v1.md      # OR similar intentional untracked files
```

If anything else shows up, clean it too.

### 3. Re-create a fresh branch and re-apply just the fix

```bash
git checkout -b kickoff/v<N>.<M>-<slug> main
```

Apply the fix using `edit` (paste the same hunks that were on the orphan branch).

Verify:

```bash
git diff --stat
git diff
```

Confirm only the intended files changed.

### 4. Verify with Playwright against the live dev servers

Vite hot-reloads SvelteKit changes. FastAPI does NOT — restart it if backend changed.

Write a small Playwright script that exercises the fix end-to-end. Capture a screenshot.

### 5. Commit with verification gate

```bash
git add <fix-files>
git commit -m "..."
git log -1 --format='%H'   # MUST be fresh; if equal to main, you didn't commit
```

### 6. Re-apply orchestrator trace notes

If `.specs/_traces.md` was reset in step 2, append a short trace entry recording what was fixed. Then:

```bash
git add .specs/_traces.md
git commit -m "chore(trace): <what>"
```

### 7. Merge to main with `--no-ff`

```bash
git checkout main
git merge --no-ff kickoff/v<N>.<M>-<slug> -m "merge: ..."
git log -1 --format='%H' main   # MUST be fresh
```

### 8. Cleanup

```bash
git branch -D kickoff/v<N>.<M>-<slug>
git status --short
git clean -fd app/test-results 2>&1 || true
```

Final status: clean working tree except intentional untracked files.

---

## Don't

- Don't re-diagnose the bug — the previous subagent got it right. Re-running the diagnosis just costs time.
- Don't carry forward orphan scratch files (test changes, inspect scripts) just because they exist in the working tree.
- Don't skip the Playwright verification step (it's the only check the test suite can't provide).
- Don't amend commits to fix bad messages — create a new commit, then rebase or squash at PR time.
