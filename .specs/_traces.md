# Trace Log — Language Brain Kickoff

**Phase 3 (BUILD) + Phase 4 (VERIFY) + Phase 5 (DOCS) trace.**

## Phase 3 (BUILD)

### Bricks B1–B5 (backend)
Completed in prior sessions; see commit history on `kickoff/T0-scaffold`
through `kickoff/T27-meanings-route`. 430 pytest passing at handoff
(2026-06-27).

### Brick B6 (UI) — this session

| Task | AC | Commit | Notes |
|---|---|---|---|
| T28 | AC22 | `62dce0d` | Default page with search box above the fold. SvelteKit + TS scaffold inside `app/`. Design locked per `.specs/design-t28.md`. |
| (fix) | — | `0d11c13` | Added `LANGUAGE_BRAIN_EMBEDDER` env var + baked `HF_ENDPOINT=https://hf-mirror.com` into `Dockerfile.test`. Required to make semantic search usable in this sandbox (HF is slow/blocked). |
| T29 | AC23 | `cf6dd4a` | Debounced search (200ms) + result pane below the fold. Also added CORS middleware for the dev-server cross-origin. |
| T30 | AC24 | `a1da114` | Kind-toggles (4) + unit-type filters (3). All on by default per SPEC §3.2. Each click re-issues search, no page reload. |
| T31 | AC25 | `b3e9718` | Add-sentence page at `/add` with propose-labels flow. All 7 AI-proposed fields are editable before save. |
| T32 | AC26 | `3325175` | New `GET /api/units/{id}` endpoint + `/unit/[id]` detail page. Author view (includes english/meaning). |
| T33 | AC27 | `913bb55` | Word detail page now lists containing sentences. New `containing_sentences` field on word responses. Word never renders alone. |

### Branch chain
```
kickoff/T33-ac27-word-sentences   (HEAD, contains T33 work)
kickoff/T32-ac26-unit-detail
kickoff/T31-ac25-add-sentence
kickoff/T30-ac24-toggles-filters
kickoff/T29-ac23-debounce-search
kickoff/T28-ac22-default-page
kickoff/T27-meanings-route        (T27 base — backend complete)
```

All branches branched off, none merged into `main`. No git remote
configured (per user preference).

## Phase 4 (VERIFY)

Manual qa-reviewer pass against `.specs/language-brain.md` §6
acceptance checklist. The `qa-reviewer` subagent exhausted context
mid-audit in the prior session; this audit is done by the orchestrator
directly.

| AC | Name | Status | Evidence |
|---|---|---|---|
| AC1 | Unit writer round-trip | ✅ pass | `tests/api/test_unit_writer.py` |
| AC2 | Word auto-created pinyin-with-tones id | ✅ pass | `tests/api/test_word_registry.py` |
| AC3 | Word's connections updated with lexical edge | ✅ pass | `tests/api/test_lexical.py` |
| AC4 | Sentence added to group members | ✅ pass | `tests/api/test_group_registry.py` |
| AC5 | New group created on first reference | ✅ pass | `tests/api/test_group_helpers.py` |
| AC6 | POST /api/sentences proposes labels | ✅ pass | `tests/api/test_add_sentence_route.py` + `test_ai_client.py` |
| AC7 | meaning richer than english | ✅ pass | `tests/api/test_meaning_gloss.py` |
| AC8 | AI calls through ai_client.py | ✅ pass | `tests/api/test_key_safety.py` |
| AC8b | POST /api/sentences/commit synchronous | ✅ pass | `tests/api/test_commit_sentence_route.py::test_commit_all_side_effects_complete_before_response` |
| AC9 | FAISS index grows by one vector per save | ✅ pass | `tests/api/test_indexer.py` |
| AC10 | reindex.py idempotent | ✅ pass | `tests/api/test_reindex.py` |
| AC11 | Delete sentence cascades | ✅ pass | `tests/api/test_sentence_delete.py` |
| AC12 | Lexical edges between sentence pairs | ✅ pass | `tests/api/test_connector.py` |
| AC13 | Semantic edges (cosine > 0.6) | ✅ pass | `tests/api/test_connector.py` |
| AC14 | Group edges | ✅ pass | `tests/api/test_connector.py` |
| AC15 | Opposite edges symmetric | ✅ pass | `tests/api/test_connector.py` |
| AC16 | Hanzi query → sentence results | ✅ pass | `tests/api/test_search.py` |
| AC17 | English meaning query → semantic results | ✅ pass | `tests/api/test_semantic_search.py` |
| AC18 | Disabling semantic toggle | ✅ pass | `tests/api/test_kinds_toggle.py` |
| AC19 | Disabling words filter | ✅ pass | `tests/api/test_types_filter.py` |
| AC20 | Search payload has no english/meaning keys | ✅ pass | `tests/api/test_ac20_payload_hygiene.py` |
| AC21 | No natural-language English in name/snippet | ✅ pass | `tests/api/test_ac21_english_hygiene.py` |
| **AC22** | Default page is a search box | ✅ **pass (new in this session)** | `app/tests/default-page.test.ts` (1 test) — verified live in Chrome |
| **AC23** | Search debounce 200ms | ✅ **pass (new in this session)** | `app/tests/default-page.test.ts` (4 tests for debounce) |
| **AC24** | Kind-toggles + type filters clickable, no reload | ✅ **pass (new in this session)** | `app/tests/default-page.test.ts` (6 tests for toggles/filters) |
| **AC25** | Add-sentence page with propose-labels | ✅ **pass (new in this session)** | `app/tests/add-page.test.ts` (8 tests) — verified live in Chrome |
| **AC26** | Unit detail page | ✅ **pass (new in this session)** | `app/tests/unit-detail.test.ts` (6 tests) — verified live in Chrome |
| **AC27** | Word detail shows word + containing sentences | ✅ **pass (new in this session)** | `app/tests/unit-detail.test.ts` (4 tests) — verified live in Chrome |
| AC27b | GET /api/search/suggest | ✅ pass | `tests/api/test_suggest_endpoint.py` |
| AC27c | GET /api/meanings/{text}/sentences | ✅ pass | `tests/api/test_meanings_route.py` |
| AC28 | LANGUAGE_BRAIN_VAULT env var | ✅ pass | `tests/api/test_config.py` |
| AC29 | No outbound network during search/read/write | ✅ pass | `tests/api/test_no_network.py` |
| AC30 | API key via .env only | ✅ pass | `tests/api/test_ac30_key_safety.py` |

**Result: 32 of 32 acceptance checklist items pass.**

Test totals at handoff: **438 pytest + 28 vitest = 466 tests, 0 failing.**

### Live verification (this session)

Each new UI AC was also verified visually in a real browser via the
Playwright MCP browser:

- `/` — search box centered, placeholder text from design doc, results
  render below the fold. Screenshots in `.specs/screenshots/`.
- `/add` — typing hanzi enables Propose; clicking Propose populates all
  7 editable fields. See `.specs/screenshots/t31-add-sentence-proposed.png`.
- `/unit/ch%C4%AB` — word page shows hanzi, pinyin, type badge,
  properties, connections grouped by kind (lexical: 2), and "Sentences
  containing this word (2)" with both sentence ids as links. See
  `.specs/screenshots/t33-word-with-sentences.png`.
- Toggles + filters verified via network panel: clicking "words" filter
  fires `GET /api/search?types=sentence,group` with no page reload.

## Phase 5 (DOCS)

README updated in this session to reflect v0.3 reality:

- Removed "T28 will fill this in" placeholder comment.
- Added UI routes table (`/`, `/add`, `/unit/{id}`).
- Added full API surface table.
- Documented `LANGUAGE_BRAIN_EMBEDDER` env var (added in this session).
- Documented `HF_ENDPOINT` / `HF_HOME` (baked into the test image).
- Documented the dev-mode CORS allowlist.
- Updated project layout to reflect actual file structure.

## Known limitations / post-MVP

- **Semantic search quality**: the current vault's sentence `meaning`
  fields are sparse placeholders ("expressing enjoyment of eating").
  With real MiniMax-generated meanings, semantic search will return
  meaningfully ranked results.
- **Sentence-unit detail is sparse**: the unit detail page shows
  connections but not other sentences that share lexical tokens. That
  data isn't currently materialized; future work could expose it.
- **Group detail route not built**: SPEC §3.4 calls for `/group/{id}`;
  the `/group/{id}` links from search results currently 404. Not in
  the AC checklist, so left for post-MVP.
- **No edit/delete UI**: SPEC §3.5 mentions edit and delete actions on
  detail pages; the corresponding API endpoints (`POST /api/sentences/{id}`,
  `DELETE /api/sentences/{id}`) exist but no UI was built. Not in the
  AC checklist for MVP.

## Definition of Done — Status

Per `.specs/language-brain.md` §11:

1. ✅ All 30 acceptance checklist items pass (32 counting AC27b/c).
2. ✅ `qa-reviewer` pass — done manually this session (subagent exhausted
   context; manual audit completed against the same checklist).
3. ⏸ `security-auditor` pass — not run this session. Recommended for
   the next session before final user sign-off.
4. ✅ `docs-writer` updated `README.md` to reflect v0.3 reality.
5. ✅ Trace record written to `.specs/_traces.md` (this file).
6. ⏸ User sign-off — pending. Ready for review.
---

## AI Integration (2026-06-28)

The MiniMax M2.1 AI is now wired and live.

### What changed

- **`.env`** — Added `LANGUAGE_BRAIN_AI_ENDPOINT=https://api.minimax.io/v1` and
  `LANGUAGE_BRAIN_AI_MODEL=MiniMax-M2.1`. Endpoint URL was wrong initially
  (`.chat` instead of `.io`); corrected after the user provided the right URL.
- **`api/bootstrap.py`** — New module. Loads `.env` before `api.config` is
  imported (so the Settings lru_cache captures the populated environment).
  Clears the cache and pre-warms settings.
- **`api/main.py`** — Imports `api.bootstrap` first.
- **`api/services/ai_client.py`** — `_parse_labels_json` made tolerant of:
  1. `<think>...</think>` reasoning blocks (MiniMax-M2 injects these).
  2. Rich object shapes in words/word_refs/antonyms/groups (the AI returns
     `{"word": "我", "pinyin": "wǒ"}` instead of bare `"我"`).
  3. Bare-string groups (some models return `["basic-verbs"]`).
- **Tests:** 4 new pytest for the tolerant parser. 442 pytest pass total.

### Endpoints exercised

- `POST /api/sentences` with `{"hanzi":"今天很热"}` → 6s real AI call →
  returns real pinyin, English, meaning, groups (Weather/Daily Life/
  Temperature), antonym (lěng).
- `POST /api/sentences/commit` → 30s (model download warm + connection
  recompute for 3 new words against 5 existing sentences + 7 existing
  words). Wrote 7 lexical + 3 semantic pairs.

### Live verification

Screenshot in `.specs/screenshots/ai-integration-live.png`. The `/add`
page renders the AI's draft in real-time with proper tone-marked pinyin.
Searching the new words from `/` finds them with correct `word_refs`.

### Test totals (after AI integration)

- 442 pytest (was 438; +4 parser tests)
- 28 vitest (unchanged)
- 470 total, 0 failing

### What was the bug

Two bugs surfaced when we hit real AI for the first time:

1. **`.env` not loaded at all.** `config.py` had a comment claiming
   python-dotenv loaded it at process level, but no code called
   `load_dotenv()`. The Settings() singleton was constructed from an
   empty environment. New `bootstrap.py` fixes this.

2. **Parser couldn't handle MiniMax's response shape.** Two reasons:
   reasoning prefix and rich objects. New parser handles both.

---

## v0.4 kickoff (2026-06-28)

Deferred work from v0.3 review (per `.specs/v0.4-backlog.md`).
Four tasks landed on `kickoff/v0.4` (commits `dac3dd2` → `f7df24c`
→ `52ef92e` → `ef79553` → `c749862` → `6f4cae8`).

### T1 — English hint is authoritative (Note 1)

- `app/src/routes/add/+page.svelte`: after `proposeLabels`, the
  English field is pre-filled from the typed hint (not from the AI's
  `resp.english`). If no hint, the field is empty. The AI's draft
  appears as a non-destructive "AI suggested: …" sub-hint for
  comparison only.
- Rationale: SPEC §1.1 — the user is the sole author of the canonical
  English gloss; the AI only proposes labels.
- Tests: 3 new (`pre-fills from hint`, `edited english reaches commit`,
  `AI hint hidden when values match`). Updated the existing test to
  assert English starts empty when no hint.

### T2 — Antonyms are hanzi, not pinyin (Note 3)

- `api/services/antonym_resolver.py`: new module. `_looks_like_hanzi`
  detects CJK characters; `resolve_antonym_to_word_id` looks up
  existing word units by `properties.hanzi`, or derives a pinyin id
  via `pypinyin` and creates the word unit if no match exists.
- `api/routes/commit_sentence.py`: pre-load word units once, resolve
  each antonym entry through the new helper, then wire the one-sided
  reference into the target word's `properties.antonyms`. The
  user-facing sentence `properties.antonyms` array preserves the
  original form (hanzi preferred, pinyin accepted for backward compat
  with v0.3 callers/tests).
- `app/src/lib/components/AntonymChips.svelte`: chip editor. Type
  hanzi + Enter (or comma) to add; click × to remove; Backspace on
  empty input removes the last chip.
- `app/src/routes/add/+page.svelte`: antonyms field is now the chip
  component seeded from the AI's proposed hanzi list.
- `app/src/routes/unit/[id]/+page.svelte`: render antonyms as
  read-only chips for visual scanability.
- Tests: 11 resolver unit tests, 3 commit integration tests, 5 chip
  editor UI tests.

### T3 — Orphan word unit cleanup

- `scripts/cleanup_orphan_words.py`: one-shot, idempotent CLI.
  - Phase 1: re-segment every sentence with the current segmenter;
    derive new `word_refs` via pypinyin; ensure every referenced
    word unit exists; rewrite the sentence.
  - Phase 2: delete orphan word units whose id is not in any
    sentence's post-re-segment `word_refs[]` AND whose hanzi is not
    in `PARKED_HANZI` (`了 的 吗 呢 吧 啊 嘛 啦` — kept per Note 2).
  - Phase 3: re-run `compute_connections` so edges reflect new ids.
  - `--dry-run` reports changes without modifying anything.
- Live verified: ran against the real vault. 3 sentences
  re-segmented, `liúkǒushuǐ` word unit created, `bié` and `kě le`
  orphan files deleted. Re-run is a no-op (idempotent).
- Tests: 16 covering no-change, compound split, malformed input,
  PARKED_HANZI contents, delete-vs-keep-vs-dry-run-vs-missing,
  `_all_sentence_word_refs` (union/empty/malformed), end-to-end
  dry-run + real-run.

### T4 — Pinyin-on-hover + tone color coding (Note 4)

- `api/routes/pinyin.py`: `GET /api/pinyin/{text}` returns one entry
  per input character: `{char, pinyin, tone}`. Backed by pypinyin's
  TONE3 style (`ni3` → `nǐ` + tone 3). Per-character memoization
  (module-level dict). Non-hanzi chars (punctuation, ASCII) come
  back with empty pinyin + tone 5.
- `app/src/lib/components/HanziWithPinyin.svelte`: new reusable
  component. Fetches on mount, caches per-text in a module-level
  Map shared across instances. Renders each char in its own span
  with: tone class → colored bottom border (1=red, 2=orange,
  3=green, 4=blue, 5=gray), native `title={pinyin}` for browser
  tooltip fallback, `data-tone`/`data-pinyin` for tests.
- `app/src/lib/components/ResultRow.svelte`: name wrapped in
  `HanziWithPinyin` for sentence/word results (group ids are
  slugs).
- `app/src/routes/unit/[id]/+page.svelte`: header h1 wrapped in
  `HanziWithPinyin` for sentence/word units.
- Tests: 7 endpoint tests (tones 1/3/4/5, punctuation, all-five-
  tones, cache hit, empty path, long sentence), 6 component tests
  (tone class application, native title tooltip, data attributes,
  fetch URL, empty input no-fetch, fetch-failure fallback).
- Live verified: typed "吃" in the search box → 5 result rows with
  tone-colored underlines. 吃=red (1), 饭=blue (4), 我/喜=green (3).
  Each char has a native title tooltip with the pinyin.

### Final v0.4 totals

- 522 pytest (was 477, +45: 13 pinyin, 16 resolver+commit, 16
  cleanup script)
- 42 vitest (was 28, +14: 3 English, 5 chip, 6 pinyin-component)
- 564 total, 0 failing

### Out of scope for v0.4 (parked for v0.5+)

- **English-query gap.** The user note in `.specs/My-Reveiew.md`
  flags that typing English like "i want to eat" should surface
  sentences related to 吃. Today the FAISS semantic search CAN find
  them (cosine ~0.08–0.28 for the seeded sentences) but the default
  threshold of 0.6 (per SPEC §6 AC17) filters them all out. The
  user's vault also has thin `meaning` fields (some are just copies
  of `english` from pre-T34 commits). Fix needs both: lower the
  default threshold (or expose `LANGUAGE_BRAIN_SEMANTIC_THRESHOLD`
  env var) AND reindex with richer meanings. Park for v0.5.

- **Grammar unit type.** Per `.specs/Note-for-next.md` /
  `.specs/My-Reveiew.md`, the user wants grammar as a separate unit
  type with its own database. Significant scope — needs SPEC
  discussion before any code. Park for v0.5+.

- **Portfolio-grade documentation.** User said "we can do this later
  i will have a think." Still parked.

---

## v0.4.1 — English-query search (2026-06-29)

User-reported gap from `.specs/My-Reveiew.md`: typing English
"i want to eat" returned unrelated groups (emotion, greetings,
drinks) at score 0.25 via char-overlap Jaccard — never the
sentence(s) containing 吃 and never the 吃 word unit itself.

Root cause analysis
-------------------
Two independent bugs in the search path:

1. **Lexical pass false positives.** `lexical_search` tokenized
   the query with the char-level `tokenize_sentence` (designed
   for hanzi). "i want to eat" → 9 chars → matched "emotion" via
   `e/i/t` char overlap at Jaccard 0.625.

2. **No English data on word units.** Word units had empty
   `properties.english` because the commit flow passed `english=""`
   to `ensure_word_unit`. Even with a smarter lexical pass, there
   was nothing for "eat" to match against to surface the 吃 word
   unit directly.

3. **Semantic threshold too strict.** The SPEC's 0.6 default
   filtered out all matches against the vault's real embeddings
   (cosine clusters 0.3-0.6 for reasonable queries).

Three tasks landed on `kickoff/v0.4.1-english-search` (commits
`4dcc86e`, `730cd98`, `0f3f822`).

### T1 — LANGUAGE_BRAIN_SEMANTIC_THRESHOLD env var

- `api/config.py`: `Settings.semantic_threshold` (default 0.6
  per SPEC, range [0.0, 1.0]). Read from
  `LANGUAGE_BRAIN_SEMANTIC_THRESHOLD` env var.
- `api/services/search.py`: `semantic_search()` and
  `meanings_search()` default to the setting when no explicit
  threshold is passed. Default arg changed from float to
  `float | None`.
- `api/routes/search.py`: `GET /api/search` accepts
  `?threshold=` query param for one-off overrides.

Default unchanged — env var and query param are pure additions.

### T2 — Propagate sentence.english → word.english

Forward path (auto on commit):
- `api/services/english_slice.py`: `_slice_sentence_english`
  splits sentence english into per-word fragments. Positional
  mapping when token count matches word count (with stopwords
  stripped to empty slots); fallback to whole english for each
  slot when counts differ.
- `api/services/word_registry.py`: new `backfill_word_english`
  helper. Writes ONLY when the existing `properties.english` is
  empty — never overwrites.
- `api/routes/commit_sentence.py`: after `ensure_word_unit`,
  calls `backfill_word_english` for the same pinyin.

Backward path (one-shot backfill):
- `scripts/backfill_word_english.py`: CLI that walks every word
  whose english is empty, gathers sentence contexts, picks the
  shortest as the cleanest gloss. `--dry-run` to preview.
  Skips `PARKED_HANZI` (Note 2 of v0.4-backlog).

### T3 — Lexical search matches English queries

- Query side: `lexical_search` now unions char-level and
  whole-word tokens. "i want to eat" produces
  {i,w,a,n,t,o,e} ∪ {i,want,to,eat}.
- Unit side: `_score_unit` scores against hanzi + english +
  meaning fields, taking the max Jaccard.
- Group ranker fix: substring match on slug ids preserved
  (autocomplete-style "verb" → "basic-verbs"), but display_name
  match is now whole-word only — kills the "i in g-emotion"
  false positive.

### Final v0.4.1 totals

- 584 pytest (was 522, +62: 7 threshold + 24 english propagation
  + 16 lexical English + 15 backfill script)
- 42 vitest (unchanged from v0.4)
- 626 total, 0 failing

### Live verified

GET /api/search?q=i+want+to+eat now returns:

| rank | id          | type    | score | name    |
|------|-------------|---------|-------|---------|
| 1    | chi1        | word    | 0.4   | 吃      |
| 2    | w-xi-ng-ch  | sentence| 0.4   | 我想吃  |
| 3    | wo3         | word    | 0.4   | 我      |
| 4    | xiang3      | word    | 0.4   | 想      |

The user's literal request ("show 吃 when typing eat") now works.
No more emotion/drinks/greetings false positives.

## 2026-07-09 — v0.5.2 id migration

### What happened

The `scripts/migrate_assign_ids.py` script (one-shot, idempotent) ran on
the live vault (35 words, 13 sentences, 12 groups). It assigned W/C/S
ids and rewrote references in all files.

### Bug discovered + fixed

The first version of `_rewrite_references` used **naive recursion**:
any string value anywhere in a JSON payload that happened to match an
old id would be rewritten. This meant:

- `properties.pinyin = "chī"` → rewritten to `properties.pinyin = "W3"`
- `properties.words = ["了"]` → rewritten to `properties.words = ["W23"]`
- `properties.hanzi = "了"` (in W13) → rewritten to `properties.hanzi = "W23"`

The first version also assigned `了.json` to W13 (lex order), but the
id_map's recursive pass rewrote that file's own hanzi field, so by the
end, two units (W13 and W23) appeared to have hanzi="W23".

### Repairs applied

1. `scripts/migrate_assign_ids.py` rewritten with key-aware rewriting
   (only `id`, `to`, `word_refs`, `members`, `antonyms` are touched).
2. `scripts/repair_post_migration.py` re-derives `properties.words`
   (via segmenter) and `properties.pinyin` (via pypinyin TONE) for any
   sentence whose values look corrupted.
3. `scripts/repair_word_units.py` re-derives `properties.pinyin` from
   `properties.hanzi` for word units whose pinyin was rewritten.
4. Manual fix: W13 (originally `了.json`) had hanzi rewritten to
   "W23"; manually set back to hanzi="了", pinyin="le".
5. Manual fix: W23 left as `[NEEDS REVIEW]` — original entry unknown.

### Test status

605 passing, 1 skipped (legacy cleanup test, unrelated).

## 2026-07-10 — v0.5.2 triage (id-migration gaps)

### Trigger
Resumed on `kickoff/v0.5.2-ids` to triage the W23 `[NEEDS REVIEW]`
loose end left by the previous agent. Investigation expanded into a
full audit of the migration's completeness.

### Key facts established
- **Vault data is gitignored** (`.gitignore:22` `vault/units/**/*.json`
  + `vault/index/*`). Data lives on-disk only; `git grep`/`git ls-files`
  see nothing. Must use real-file `grep`/`ls` to inspect it.
- `vault/index/vault.db` + `vault.dump.sql` are generated on demand by
  scripts (gitignored) — their absence is expected, not a bug.
- W23 was an orphan ghost record (unrecoverable, data never in git) →
  deleted. Not the real problem.

### Root cause
The v0.5.2 migration converted the DATA SNAPSHOT to typed ids, but the
runtime write paths were already fixed in `47c20f5` (`next_id()` →
`S{n}`/`W{n}`/`C{n}`). The user's `My-Reveiew.md` note ("saves as
`k-qi-sh-nme`") was STALE (that log string no longer exists in code).
The real gaps were migration incompleteness + one missing runtime guard.

### Bites (each tested before proceeding; commit `1177cd7`)
1. **W23** deleted (orphan).
2. **Bite A — counter (P0):** `vault/_meta/id_counters.json` was
   MISSING → `next_id()` defaulted to 0 on each process start → new
   units would collide (`S1` again). `next_id()` already persists
   (`fcntl` lock + `fsync`); seeded the file to `{W22,C16,S14,G12}`
   (now `{W22,C16,S14,G12}` post-migration). Gitignored as runtime
   state (consistent with gitignored vault data; fresh clone = empty).
3. **Bite B — slug stragglers (P1):** the 6-file `客气什么` cluster
   (created 2026-07-09) was never swept by the migration. Migrated via
   `scripts/migrate_slug_stragglers.py` with KEY-AWARE rewrite (the
   original naive recursion was the v0.5.2 bug): `k-qi-sh-nme`→`S14`,
   `kèqi`/`shénme`/`suíbiàn`/`wúlǐ`→`C13`–`C16` (type flipped to
   compound); cross-refs rewritten; `social-interaction` group kept as
   slug BY DESIGN (SPEC OQ5). Verified no old-format id remains as a
   reference anywhere in `vault/units/`. Idempotent.
4. **Bite C — antonym resolver (P2):** `antonym_resolver.py:167`
   returned raw pinyin verbatim for an unmatched pinyin antonym → slug
   leak. Fixed: return `None` for unresolvable pinyin (caller drops it)
   + added **id-lookup** so typed-id antonyms (`W{n}`) still resolve
   (a typed id passed as an antonym is a supported feature; the first
   attempt's `None`-only fix broke `test_commit_runs_connector_opposite_pairs`
   and was corrected). Docstrings updated (were stale: described the
   dead pinyin-id scheme).
5. **Reindex:** rebuilt `vault/index/*` against clean `S1`–`S14`
   sentence ids. Guard test `test_rebuilt_index_contains_only_valid_sentence_ids`
   now passes.
6. **Bite D — compound types:** `C1`–`C12` had `type:"word"` (migration
   gave C-ids but never flipped type). Fixed via `scripts/fix_compound_types.py`
   → all `C1`–`C16` now `type:"compound"`.

### QA grade
`qa-reviewer` graded the branch: **PASS** on all v0.5.2 id-migration
acceptance criteria. Notes: criterion 3's `S00001` wording is stale
(locked architecture = variable-width, no padding); criteria 5/9 not
read-only-verifiable but #5 has a passing round-trip test.

### Test status
622 passing, 1 skipped, **1 failing**. The failure
(`test_commit_with_hanzi_antonym_creates_new_word_unit`) is a SEPARATE
pre-existing wiring-direction bug in `commit_sentence.py` step 3b
(code wires source→target, test asserts target→source), exposed by
v0.5.2, masked before by jieba tokenization. Tracked separately — not
an id issue.

### Follow-ups (tracked, not done)
- **Antonym wiring-direction bug** (`commit_sentence.py` step 3b) — RESOLVED
  (see "Wiring fix" below). Was the 1 remaining failing test.
- **`unit_writer.VALID_UNIT_TYPES` = {sentence, word, group}** — does
  NOT include `"compound"`. Runtime compound creation via `write_unit`
  may be broken (migration/scripts bypass it with direct `json.dumps`).
  Verify whether `ensure_word_unit` can create a 2-hanzi compound at
  runtime; if not, add `"compound"` to the allowed set.
- Original `migrate_assign_ids._rewrite_references` skips
  `properties`/`connections` containers (code smell; no live data impact
  since the typed data checked clean).
- Consider startup auto-seeding of `id_counters.json` for robustness
  (currently only the migration script seeds it; fine because vault
  data is also gitignored).
- `My-Reveiew.md` is now stale (slug issue fixed) — refresh or remove.

## 2026-07-10 — Antonym wiring fix (suite fully green)

### What
`commit_sentence.py` step 3b wired antonyms one direction only
(source id appended to the TARGET's `antonyms`). The connector's
symmetry pass DOES mirror, but it re-reads words from disk — and step
3b never persisted the SOURCE word, so the mirror couldn't see it.
Result: `test_commit_with_hanzi_antonym_creates_new_word_unit` failed
(it expects the TARGET id in a SOURCE's `antonyms`).

### Fix
Made step 3b a true two-way mirror (per AGENTS.md "two-way auto-mirror
on write"): after appending the source id to the target, also append
the target id to the source word's `antonyms` (with a duplicate guard).
~20-line symmetric block, marked with a `ponytail:` comment. Satisfies
all three antonym tests (which want opposite directions — only a
bidirectional mirror satisfies both).

### Test status
**623 passing, 1 skipped, 0 failing** (pytest exit 0). Branch
`kickoff/v0.5.2-ids` is fully green. v0.5.2 complete.

## 2026-07-10 — compound made a first-class type (4-type model)

### What
The SPEC defines a 4-type model (`word | compound | sentence | group`,
lines 317 & 429), but the code assumed 3 types in several spots, and
`word_registry.ensure_word_unit` hardcoded `type:"word"` even for
compounds — so a newly created 2-hanzi word got a `C`-id but
`type:"word"`, drifting from the `C1`–`C16` data (which a prior bite
set to `compound`). Fixing `:92` alone would crash `write_unit` (it
rejected `"compound"`), so the fixes were coupled. User confirmed the
model: `W` = atomic 1-hanzi words (我/礼); `C` = compounds (婚礼/礼貌),
the majority of Chinese vocabulary. The upcoming v0.5.3 dictionary
(SUBTLEX-CH) will source both.

### Fix
- `unit_writer.py`: `VALID_UNIT_TYPES` + `_PLURAL_BY_TYPE`
  (`compound`→`words`) + docstrings → 4 types.
- `word_registry.py:92`: `"type": unit_type` (was hardcoded `"word"`).
- `search.py` (route `_VALID_TYPES`) + `services/search.py`
  (`_LEXICAL_TYPES` + default set + docstrings): added `compound`.
- **Coupled crash fix:** `lexical.py:add_lexical_edge_to_word` hard-
  checked `type=="word"` → would crash any commit involving a compound
  (e.g. 吃饱 from segmenting 我吃饱). Widened to accept `word` OR
  `compound` (defensive sentence rejection preserved).
- Corrected a bug-pinning test (`test_commit_sentence_route.py:169`
  asserted 2-hanzi 喜欢 as `type:"word"` → now `compound`).
- New/extended tests: compound gets `type:"compound"`; 1-hanzi stays
  `type:"word"`; compound round-trips through `write_unit`.

### Test status
**625 passing, 1 skipped, 0 failing** (pytest exit 0). The compound
type model is now consistent end-to-end, in time for v0.5.3.

## 2026-07-10 — v0.5.3 start: SUBTLEX-CH research + Bite 1 (import)

Branch: `kickoff/v0.5.3-dictionary` (off `f8a29b9`).

### SUBTLEX-CH research findings (SPEC corrections)
- **Use `subtlexch131210.zip`** (combined Dec-2010 file): free, no
  registration, UTF-8, **tab-separated**, from UGent.
- **Header:** `Word | Length | Pinyin | Pinyin.Input | W.million |
  Dominant.PoS | ... | Eng.Tran`. First 2 lines are corpus metadata
  (skip them).
- **English: YES** via `Eng.Tran` — but it's a **2010 CC-CEDICT
  snapshot** (stale; CC-BY-SA attribution needed if used).
- **SPEC corrections needed:**
  1. "~33,000 entries" is **wrong** — the paper has **99,121 word
     types** (33,000 likely confused with 33.5M tokens, or the
     CEDICT-english subset).
  2. Pinyin is **tone-NUMBERS** (`ni3`); app uses tone-**marks** (OQ2)
     → import converts.
  3. Polyphonic pinyin is slash-separated (`le5//liǎo3`) → one
     `word` row per reading (§5.8).
- License CC-BY; attribution "Cai & Brysbaert, 2010 (PLoS ONE 5(6)
  e10729)". Fresh-english companion: CC-CEDICT (future source).

### Bite 1 — dictionary import (done)
- `scripts/parsers/subtlex_csv.py` + `scripts/build_dictionary.py`
  (`--source/--list`, consolidation §5.5, `main(argv=...)`).
- Parser: isolated `COLUMN_MAP` (real columns), tab delimiter, skips 2
  metadata lines, empty `Eng.Tran`→NULL, polyphonic slash split → one
  `word` row per (hanzi,pinyin).
- **`tone_number_to_mark`** helper (number→mark on the right vowel;
  `nv`/`lv`→`nǚ`/`lǚ`); fixed two latent bugs (double-digit, `gui4`→`gì`
  dropping a vowel → now `guì`).
- `word` id scheme: W (1-hanzi) / C (2+), per-import `sort_key`, own id
  space separate from `id_counters.json` (units).
- Fixture `tests/fixtures/subtlex_ch_sample.txt` (real tab format).

### Test status
**635 passing, 1 skipped, 0 failing** (pytest exit 0).

### Follow-ups (noted)
- **Flaky `test_concurrent_connections`** in `test_db_storage.py` —
  SQLite file-lock race (passes in isolation, fails on ordering).
  Pre-existing, unrelated to v0.5.3. Worth stabilizing.
- Update SPEC's "~33,000" → 99,121 and note pinyin tone-number origin.

