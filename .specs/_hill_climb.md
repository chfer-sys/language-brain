# Hill Climbing Log — Loop 4

Records patches proposed and applied to the project-level harness (SPEC template, AGENTS.md, .opencode/ files) based on trace analysis.

---

## 2026-07-24 — v0.9 deploy failure clusters

**Traces analyzed**: `.specs/_traces.md` lines 1200-1441 (2026-07-24 deploys)

**Failure clusters identified**:

1. **docker inspect %q quotes** — 3 occurrences in 4 deploys. Template emits literal quotes → mock_mode:true.
2. **docker inspect preserves stale env** — blocked model switch (deepseek→mimo) without manual override.
3. **Server clone branch mismatch** — SKILL.md hardcoded `main` but live server runs `kickoff/v0.9-integration`.
4. **Port template protocol suffix** — produces `8000/tcp:8000` instead of `8000:8000`.
5. **Leaked secrets in trace files** — AI key in _traces.md, caught by pre-commit hook.

**Patches proposed**: 5 (all harness-level, no application code)

**Patches applied** (user-approved): 4

- **Patch 1**: %q quotes fix — changed `%q` to `%s` in env template + added mandatory sed strip step (2.5)
- **Patch 2**: Selective env override — added step 2.6 for editing `/tmp/lb-env.sh` before recreate
- **Patch 3**: Branch preservation — detect current branch via `git rev-parse --abbrev-ref HEAD` instead of hardcoding `main`
- **Patch 4**: Port template fix — strip protocol suffix via `(split $p "/")` in template

**Patch deferred** (user declined):

- **Patch 5**: Secret-leak guardrail — add rule to AGENTS.md about never logging secrets to trace files. User did not select this patch.

**Commit**: `d416eaf` on `kickoff/v0.9-integration`

**Re-verification**: N/A (harness doc change, not code). Next deploy using the updated skill should confirm the fixes work.

**Expected effect**: The next deploy using the safe-server-deploy skill should:
- Not require manual sed strip (step 2.5 does it automatically)
- Not require manual env override edits (step 2.6 documents the pattern)
- Preserve the current branch instead of forcing `main`
- Produce valid `-p 8000:8000` without protocol suffix
