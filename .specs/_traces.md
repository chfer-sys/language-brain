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
