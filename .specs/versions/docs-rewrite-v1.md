# Docs Rewrite — v1

**Audience:** `docs-writer` subagent
**Owner:** the user (Language Brain)
**Date:** 2026-07-15
**Status:** approved; ready for `docs-writer` to consume

---

## 1. Goal

Replace today's minimal `README.md` (6.3 KB, mostly install commands) and the
single-page `docs/runbook.md` with a complete, human-language documentation
set covering: install, usage, architecture, the vault, every script, the
runbook, security, a glossary, and version release notes.

After this lands, a reader who has never opened a terminal can:
- know what Language Brain does in one paragraph,
- follow a 4-step Quick start,
- find the answer to "where is my data" without opening the source code,
- look up a term they don't recognize,
- run any of the 18 utility scripts without reading its source.

---

## 2. Tone — UX writer, not developer writer

**Voice:** imagine explaining the app to an intelligent non-engineer who uses
Notion or Obsidian but has never opened a SQLite browser. They want confident
language, not jargon. They want to know WHAT and WHY before HOW.

**Worked example**

Bad (developer voice):
> The vault is an on-disk SQLite database (`vault/index/vault.db`) backed by a
> line-oriented SQL dump file (`vault/index/vault.dump.sql`) that serves as
> the canonical version-controlled mirror; the binary DB is gitignored.

Good (UX-writer voice):
> Your sentences, words, and groups live in a folder called `vault/`. Inside
> that folder, the actual data is a single file — `vault/index/vault.db` —
> which the app reads and writes. To keep your history reviewable and your
> data restorable, every save also produces a plain-text mirror called
> `vault.dump.sql` that's checked into git. If anything goes wrong, one
> command rebuilds the database.

Rules of thumb:
- Lead with what the user sees (`vault/`), not the implementation
  (`SQLite database`).
- One technical term per paragraph; define it inline on first use.
- Every factual claim that elaborates something gets a cross-link.
- No emoji.
- Sentences under ~25 words on average. Break long sentences.

---

## 3. Non-goals (DO NOT do these)

- DO **not** rewrite `.specs/language-brain.md` (the master technical SPEC).
  It is the canonical source of truth; `docs/` cross-links INTO it.
- DO **not** change code, refactor, or add scripts.
- DO **not** regenerate `vault/index/vault.dump.sql`, run tests, start the
  server, or commit anything other than new/changed docs files.
- DO **not** use emojis anywhere.
- DO **not** add a "Contributing" page — this is a solo project.
- DO **not** invent API endpoints, scripts, or features. If a script or
  endpoint is not in the source tree, do not document it.
- DO **not** quote or paraphrase the user's vault-storage discussion
  (Tier 1/2/3 was deferred on 2026-07-14). Treat the docs as if the vault
  topic is untouched.

---

## 4. File layout

```
README.md                            ← rewrite, ≤ 80 lines
CHANGELOG.md                         ← release notes per version
docs/
├── README.md                        ← index of every doc page
├── architecture.md                  ← three-part system diagram + data flow
├── installation.md                  ← fresh install, 2nd machine, Docker / no-Docker
├── usage.md                         ← learner tour: add → search → organize
├── vault.md                         ← what the vault is, where it lives, backup, restore
├── scripts.md                       ← every script: what / when / how / risk
├── runbook.md                       ← existing — append §10 + §11 only
├── glossary.md                      ← terms defined in plain English
├── security.md                      ← AI-key handling, .gitignore behavior
└── release-notes/
    └── v0.5.5.md                    ← one page per version (plain English)
```

### 4.1 Per-file brief

**`README.md`** — rewrite, ≤ 80 lines:
1-paragraph pitch · 4-step Quick start · "Where to go next" table linking to
the top 5 doc pages · 1-line license/status footer (`Personal project,
version 0.5.5, see CHANGELOG`). Strip the env-vars table (move to
`docs/installation.md`). Strip the API table (move to `docs/usage.md`).

**`CHANGELOG.md`** — new:
One bullet per version, newest-first. Plain English; no commit hashes. Draw
from `.specs/versions/v0.5.*.md` titles + first-paragraph summaries. Skip
versions that never shipped.

**`docs/README.md`** — index page:
Title · 1-sentence description of the docs · table of contents linking to
every doc, README, and CHANGELOG · "Reading paths" with 3 recommended
orders (learner · deployer · operator).

**`docs/architecture.md`** — what the three parts are and how data flows:
- 1-paragraph on each of: backend (FastAPI, `api/`), frontend
  (SvelteKit, `app/`), vault (`vault/` + FAISS index).
- ASCII or mermaid diagram showing: user → frontend → backend → vault →
  FAISS index → results.
- 1-paragraph on the v0.5 storage model (SQLite binary + git-tracked SQL
  dump mirror). Cross-link to `docs/vault.md`.
- Cross-link to `.specs/language-brain.md §1, §2, §5.1`.

**`docs/installation.md`** — three install paths, each a 5-step recipe:
- (A) Editable pip install + local dev (the existing README Quick start).
- (B) Docker test image (`Dockerfile.test`).
- (C) Production deploy via `ops/deploy.sh` to the LAN server.
- "Common pitfalls" table: HF mirror, `.env` vs `.env.example`, first-build
  FAISS delay, embedder mode (`hashing` vs `real` vs auto).

**`docs/usage.md`** — the learner tour:
- "The loop in 5 steps" narrative: add a sentence → propose labels → save →
  search → organize.
- Each step is 1 sentence + a link to the API endpoint or UI route.
- Pull the route table from current `README.md` §UI routes.
- Pull the API surface table from current `README.md` §API surface.

**`docs/vault.md`** — the data owner's view:
- "Where your data lives" — annotated `tree` of `vault/` (top 3 levels).
- "What's on disk vs. in git" — table with one row per artifact under
  `vault/`: filename · what it is · tracked? · how to regenerate.
- "Backups" — describe the recommended Tier 1 setup (push `vault.dump.sql`
  to a private GitHub repo on a cron) AS IF the user has set it up.
  Note: actual setup was deferred 2026-07-14; this is "the docs that future
  setup will follow."
- "Restore" — `cat vault/index/vault.dump.sql | sqlite3 vault/index/vault.db`
  + `python scripts/reindex.py`. Explain why both are needed.

**`docs/scripts.md`** — the centerpiece:
- "Quick reference" table at the top: `script name → one-liner purpose`
  (one row per script, 18 rows).
- One section per script with this exact format:
  - **What it is** — 1 sentence.
  - **When to run it** — 1 sentence ("after editing sentence JSON by hand",
    "when search results look stale", "when you see X in logs", etc.).
  - **How** — one example command, with the actual flags it accepts
    (`--vault-root`, `--dry-run`, etc., pulled from the script's `argparse`).
  - **Touches** — does it write to `vault/units/`? `vault/index/`? git
    history? runtime state (`_meta/`)? Be specific.
  - **Reversible** — yes/no, and how. (e.g. `cleanup_orphan_words.py` is NOT
    reversible without a git reflog; `dump_vault_sqlite.py` IS reversible.)
- Source: read each script's module docstring (the `"""..."""` block at
  the top). Don't invent flags that aren't there.
- Today's 17 utility scripts (run `ls scripts/*.py scripts/*.sh` to count; ignore `__init__.py` and `parsers/`):
  `backfill_word_english.py`, `benchmark_search.py`, `build_dictionary.py`,
  `check_no_secrets.sh`, `cleanup_orphan_words.py`, `dump_vault_sqlite.py`,
  `fix_compound_types.py`, `fix_dangling_refs.py`, `migrate_assign_ids.py`,
  `migrate_json_to_sqlite.py`, `migrate_slug_stragglers.py`,
  `reconcile_to_dict_ids.py`, `reindex.py`, `repair_post_migration.py`,
  `repair_word_units.py`, `vault_check.py`. Plus `ops/deploy.sh`.

**`docs/runbook.md`** — extend the existing file:
- Existing content stays.
- Confirm §10 (deploy workflow) is there; if not, append it.
- Add §11 "Common incidents" — vault corruption (`vault_check.py` first),
  FAISS drift (reindex), secret leak (`scripts/check_no_secrets.sh` first,
  then rotate), broken search (test in `/api/search?q=` and `/healthz`).

**`docs/glossary.md`** — alphabetical:
Each term is 2-3 sentences in plain English, with a cross-link to the
deeper section.
Required terms (at minimum):
`vault`, `unit`, `sentence`, `word`, `compound`, `group`, `connector`,
`embedding`, `FAISS`, `semantic threshold`, `libSQL`, `jieba`, `pypinyin`,
`mock mode`, `embedder mode`, `HF mirror`, `id scheme (W/C/S/G)`, `antonym
(auto-mirror)`, `connector kind`.

**`docs/security.md`** — secrets and the pre-commit guard:
- "Where your secrets live" — `.env` (gitignored), `ops/deploy.sh.env`
  (gitignored, optional), `app/.env` (tracked, contains only the public LAN
  URL — never a key).
- "The secret guard" — `scripts/check_no_secrets.sh` and the pre-commit
  hook wiring (`ln -s ../../scripts/check_no_secrets.sh .git/hooks/pre-commit`).
  Currently lives in README §Pre-commit secret guard; move it here.
- "If your key leaked" — rotate the AI key, clear `.git/reflog`, reset
  `ops/deploy.sh.env`, redeploy with `ops/deploy.sh`. Cross-link to
  `docs/runbook.md §11`.

**`docs/release-notes/v0.5.5.md`** — one page per shipped version:
- Plain English paragraph: "what changed and why it matters to you."
- Bullet list of user-visible changes only (skip internal refactors that
  don't ship a user-observable effect).
- Cross-link to the SPEC for technical detail. Use the existing
  `.specs/versions/v0.5-storage-and-dict.md` and
  `.specs/versions/v0.5-bounded-tags-and-optional-ai.md` as the source of
  truth for v0.5.x. Do NOT link to `.specs/versions/v0.5.5.md` — it does
  not exist in the source tree (per v0.5.5 sub-version, the technical
  details live inside `v0.5-storage-and-dict.md`).
- For `v0.5.5` specifically: search parity check, no API changes.
- If a v0.4 or earlier version warrants a page, add one too.

---

## 5. Source-of-truth map

Every docs page MUST cite the SPEC section it draws from. Use these mappings:

| doc page | primary source |
|---|---|
| `README.md` (Quick start + pitch + Where-to-go-next) | `.specs/language-brain.md §1, §3, §5.5`; current `README.md` |
| `docs/architecture.md` | `.specs/language-brain.md §1, §2, §5.1` |
| `docs/installation.md` | `.specs/language-brain.md §5`, current `README.md`, `pyproject.toml` |
| `docs/usage.md` | `.specs/language-brain.md §3, §5.2`; current `README.md` §UI routes + §API surface |
| `docs/vault.md` | `.specs/language-brain.md §2.5, §5.1 (storage subsection)`, `.gitignore` |
| `docs/scripts.md` | `scripts/*` docstrings, `.specs/versions/v0.5.1-*.md` for migration rationale |
| `docs/runbook.md` | existing `docs/runbook.md`; `docs/runbook.md §10` if present |
| `docs/glossary.md` | `.specs/language-brain.md §2` |
| `docs/security.md` | `AGENTS.md`, `pyproject.toml`, `scripts/check_no_secrets.sh`, `.gitignore` |
| `docs/release-notes/v0.5.5.md` | `.specs/versions/v0.5.*.md` |

When a docs page elaborates a term or feature that lives in another docs
page, it MUST link to that page (not just the SPEC section).

---

## 6. Cross-link & link-integrity rules

- Every file in `docs/` MUST be linked from `docs/README.md`.
- Every internal link MUST use `.md`-relative paths (e.g.
  `[vault](vault.md)`, not absolute URLs).
- Every link to a SPEC section MUST use the markdown fragment that exists
  in the actual file (`§5.1`, not `storage layer details`).
- No link points to a 404. If the target file does not yet exist, do not
  link it — your deliverable creates the target file.

---

## 7. Acceptance criteria (for `qa-reviewer`)

1. Every file in §4 file layout exists, has non-empty content, and is
   linked from `docs/README.md`.
2. `README.md` is ≤ 80 lines AND contains: a 1-paragraph pitch, the
   4-step Quick start, a Where-to-go-next table.
3. `docs/scripts.md` has entries for every utility script in `scripts/`
   PLUS `ops/deploy.sh`. Count must equal `$(ls scripts/*.py scripts/*.sh
   | wc -l) + 1`. One section per script in the §4.1 format.
   `scripts/`, each following the 5-field format in §4.1.
4. `docs/glossary.md` defines at least these 19 terms: vault, unit,
   sentence, word, compound, group, connector, embedding, FAISS, semantic
   threshold, libSQL, jieba, pypinyin, mock mode, embedder mode, HF mirror,
   id scheme (W/C/S/G), antonym (auto-mirror), connector kind.
5. `docs/vault.md` has a "What's on disk vs. in git" table covering every
   artifact in `vault/` (recursively under `index/`, `units/`, `_meta/`).
6. `docs/security.md` documents the pre-commit secret-guard hook wiring.
7. Zero emojis across all docs files.
8. No docs page rewrites or contradicts `.specs/language-brain.md`; where
   docs cross-link into SPEC, the cited section exists in the SPEC.
9. No code changes in the diff (`git diff main -- ':!*.md' ':!docs'` is
   empty).
10. Internal `.md`-relative links resolve in a `grep -rn '\](\.\./.*\.md'`
    pass (every link target file exists).

---

## 8. Out of scope (escalate if needed)

- Vault storage topology (Tier 1/2/3). User deferred 2026-07-14.
- Resurrecting v0.6 docs (deleted 2026-07-14, see `docs/runbook.md §11.5`
  or memory).
- New scripts or new endpoints.
- A `CONTRIBUTING.md`.
- Translated docs (other languages).
- Auto-generated API reference (this rewrite is human-curated, OpenAPI not
  included).

---

## 9. Deliverable

One branch off `main`: `kickoff/docs-rewrite-v1`.

One commit unless the doc-writer finds a logical split (e.g. separate
"docs scaffold" from "scripts catalog"); if so, ≤ 4 commits total.

PR description: list every file added/modified with 1-line purpose each.

DO NOT auto-merge. The orchestrator dispatches `qa-reviewer` and
`security-auditor` separately.
