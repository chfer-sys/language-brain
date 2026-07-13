# Fix Plan — Functional Test Gaps

**Status:** PLANNED
**Date:** 2026-07-13
**Based on:** `.specs/functional-test-session.md` gap analysis

---

## Phase 1: P0 Fixes (executor — one branch per fix)

**Dependency graph:**
```
P0 #3 (tone-mark normalization)
    ↓ (required by — same pipeline)
P0 #2 (pinyin ranking)
P0 #1 (semantic threshold)  ← independent, parallel
```

**Execution order:** Steps 1 and 2 can run in parallel (different files). Step 3 must follow Step 1 (same service, same tokenization pipeline).

---

### Step 1: Tone-marked pinyin normalization

- **Agent:** executor
- **Branch:** `fix/p0-tone-mark-normalization`
- **Files to touch:**
  - `api/services/lexical.py` — add `_strip_diacritics()` helper and export
  - `api/services/search.py` — import `_strip_diacritics`, apply before `tokenize_sentence` in both `lexical_search` (Step 1 of the function) and `group_search` (tokenization step)
- **What to do:**

  1. In `lexical.py`, add at module level:

     ```python
     #ponytail: basic Unicode deconstruction — valid for all 6 tone-marked vowels
     _DIACRITIC_MAP = {
         'ā': 'a', 'á': 'a', 'ǎ': 'a', 'à': 'a',
         'ē': 'e', 'é': 'e', 'ě': 'e', 'è': 'e',
         'ī': 'i', 'í': 'i', 'ǐ': 'i', 'ì': 'i',
         'ō': 'o', 'ó': 'o', 'ǒ': 'o', 'ò': 'o',
         'ū': 'u', 'ú': 'u', 'ǔ': 'u', 'ù': 'u',
         'ǖ': 'ü', 'ǘ': 'ü', 'ǚ': 'ü', 'ǜ': 'ü',
         'ń': 'n', 'ň': 'n',  # ēāén (rare but present in some romanizations)
     }

     def _strip_diacritics(text: str) -> str:
         """Return text with all tone-marked vowel diacritics replaced by their base letter."""
         out = []
         for ch in text:
             out.append(_DIACRITIC_MAP.get(ch, ch))
         return ''.join(out)
     ```

  2. In `lexical_search` (`search.py`), before `char_tokens = tokenize_sentence(query)` (line ~468), add:

     ```python
     # Normalize tone-marked pinyin to plain ASCII before tokenization.
     # This lets "wǒ xiǎng chī" match the same as "wo xiang chi".
     normalized_query = _strip_diacritics(query)
     ```

     Then use `normalized_query` for all downstream tokenization and scoring.

  3. In `group_search` (`search.py`), before the `re.findall(r"[A-Za-z0-9]+", query.lower())` line (line ~662), apply `_strip_diacritics` to the query first.

- **Test:** `GET /api/search?q=wǒ%20xiǎng%20chī&kinds=lexical` should now return S9 我想吃 in position 1 with score ~1.0 (exact multi-syllable match, same as `?q=我想吃`). Before fix, D4 shows groups at top 3 and S9 is absent.
- **Dependencies:** none
- ** ponytail note:** The `_DIACRITIC_MAP` is a fixed-size dict for the 6 vowel letters × 4 tones + ü variants + n-accent variants. No external library needed. Covers all pinyin tone marks in common use.

---

### Step 2: Lower semantic threshold default

- **Agent:** executor
- **Branch:** `fix/p0-semantic-threshold`
- **Files to touch:**
  - `api/config.py` — change `semantic_threshold` default from `0.6` to `0.3`
- **What to do:** In `Settings.semantic_threshold`, change `default=0.6` to `default=0.3`. The observed max semantic score in testing is 0.509; a threshold of 0.3 allows those results through while still filtering noise. The docstring description (`"lower it (e.g. 0.4) for vaults with thin meaning fields where English queries cluster around 0.3–0.5"`) already describes exactly this situation.
- **Test:** `GET /api/search?q=i%20want%20to%20eat&kinds=semantic` (no `?threshold=`) should now return semantic results (previously returned 0 at default 0.6). Confirm B2's `?threshold=0.1` results are now accessible at default threshold.
- **Dependencies:** none (independent of Steps 1 and 3)
- **ponytail note:** This is a one-character numeric change. No new logic, no new dependencies.

---

### Step 3: Pinyin multi-syllable ranking boost

- **Agent:** executor
- **Branch:** `fix/p0-pinyin-ranking`
- **Files to touch:**
  - `api/services/lexical.py` — export `_strip_diacritics` (already added in Step 1)
  - `api/services/search.py` — add pinyin-aware scoring path in `_score_unit`
- **What to do:**

  The current scoring pipeline tokenizes everything character-by-character, which makes multi-syllable pinyin queries (e.g. "wo xiang chi") score against hanzi/english/meaning with no syllable coherence signal. The fix adds a pinyin-aware scoring path inside `_score_unit`:

  1. Detect whether the query is a pinyin string (all-ASCII, no CJK): check `query_tokens` contents or pass a flag.
  2. If pinyin query: also tokenize the unit's `properties.pinyin` (after diacritic stripping) into syllables by splitting on whitespace.
  3. Compute a syllable-level Jaccard between query syllables and stored syllables.
  4. Take `max(existing_score, syllable_jaccard * 1.5)` — the 1.5× bonus rewards consecutive full-syllable matches over fragment overlap.

  Concrete implementation in `_score_unit`:

  ```python
  # After existing score computation (best_score from hanzi/english/meaning)
  # Add pinyin path for ASCII-only queries
  pinyin = properties.get("pinyin")
  if isinstance(pinyin, str) and pinyin:
      # Strip tone marks and split into syllables
      plain = _strip_diacritics(pinyin)
      pinyin_tokens = plain.split()  # ['wo', 'xiang', 'chi']
      if pinyin_tokens and pinyin_tokens != ['']:
          # Only use pinyin score if query tokens look like syllables (not CJK chars)
          # A pinyin query token is a lowercase ASCII run of length 2-6
          pinyin_query = ' '.join(query_tokens)
          if re.fullmatch(r'[a-z\s]+', pinyin_query):
              py_jaccard = jaccard(query_tokens, pinyin_tokens)
              if py_jaccard > 0:
                  best_score = max(best_score, py_jaccard * 1.5)
  ```

  Note: `_score_unit` currently receives `query_tokens` (character-level), not the raw query string. The pinyin detection uses the token shape: pinyin syllables are ASCII runs of length 2-6. If `query_tokens` are all such runs (e.g., `['wo', 'xiang', 'chi']`), we treat the query as pinyin. This avoids needing to pass the raw query through.

  Also: after adding the pinyin path, the result for "wo xiang chi" should have S9 scoring significantly higher than the current 0.067, pushing it to position 1 or 2.

- **Test:** `GET /api/search?q=wo%20xiang%20chi&kinds=lexical` — S9 should appear at position 1 or 2 (not 13). Score should be > 0.5 for exact multi-syllable match. Verify S27 no longer outranks S9.
- **Dependencies:** Step 1 (tone-mark normalization must be in place before pinyin scoring can work — diacritics in stored pinyin must be stripped for the matching to work)

---

## Phase 2: P1 Fixes (executor)

**Steps 4 and 5 are independent; can be parallelized.**

---

### Step 4: Long input length validation

- **Agent:** executor
- **Branch:** `fix/p1-long-input-validation`
- **Files to touch:**
  - `api/routes/search.py` — add input length check in `search()` route
- **What to do:** After `q: str` is parsed, add a guard:

  ```python
  if len(q) > 200:
      from fastapi import HTTPException, status
      raise HTTPException(
          status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
          detail="Query too long (max 200 characters).",
      )
  ```

  This returns a proper 422 (not 400) with a descriptive message, matching FastAPI conventions. The frontend already debounces and the user won't see this in normal use; it's a guard against malformed clients or curl mistakes.

- **Test:** `GET /api/search?q=<201 chars>` returns 422 with JSON `{"detail": "Query too long (max 200 characters)."}`. `GET /api/search?q=<200 chars>` returns 200 with results.
- **Dependencies:** none
- **ponytail note:** 200 chars is plenty for any meaningful query; this covers all real use cases while preventing the 1000-char crash.

---

### Step 5: Word results include sentence context

- **Agent:** executor
- **Files to touch:**
  - `api/schemas.py` (or wherever `SearchResultItem` is defined) — add `containing_sentences: list[str] | None` field to word results
  - `api/services/search.py` (`_assemble_hits` or a new wrapper) — for word hits, look up sentences that contain this word via the connections/lexical edges, extract hanzi, and populate `containing_sentences`
  - `app/src/lib/components/ResultRow.svelte` — render sentence context for word results (e.g., show one example sentence below the word's hanzi+pinyin row, or as a suffix)
  - `app/src/lib/api.ts` (or wherever `SearchResult` type is defined) — add `containing_sentences` to the client type
- **What to do:**

  1. **Schema change:** In `SearchResultItem` (Pydantic model), add `containing_sentences: list[str] | None = None`. The field is optional so existing sentence/group results are unaffected.

  2. **Service change:** In `_assemble_hits` (or a new `assemble_hits_with_context` function), when `unit_type == "word"`:
     - Read the word unit's `connections` list (field: list of `{"to": sentence_id, "kind": "lexical", ...}` dicts)
     - For each connection with `kind == "lexical"`, read the referenced sentence unit and extract its `properties.hanzi`
     - Return up to 3 example sentence hanzi strings (or just the count + first one for the snippet)
     - Populate `SearchHit` with a new `containing_sentences` field

  3. **Frontend change:** In `ResultRow.svelte`, for `result.type === 'word'` and `result.containing_sentences?.length`, show a small text below the snippet: e.g., `"e.g. 我想吃"` or a count badge `"4 sentences"`.

  4. **Type change:** Update `SearchResult` type in `app/src/lib/api.ts` to include `containing_sentences?: string[]`.

- **Test:** `GET /api/search?q=想&types=word` — word results (e.g., W32 想) should now include `containing_sentences` in the JSON response. The frontend displays at least one example sentence for word results. Verify C2 test from the session now shows sentence context instead of bare hanzi+pinyin.
- **Dependencies:** none (P1, independent of P0)
- **ponytail note:** The minimal version is adding `containing_sentences` to the response and rendering the first one in `ResultRow`. Full pagination/filtering of contained sentences is out of scope.

---

## Phase 3: P2 Fixes (executor — optional, time-permitting)

---

### Step 6: `kinds=` empty string treated as "no kinds" (not "all kinds")

- **Agent:** executor
- **Branch:** `fix/p2-kinds-empty-string`
- **Files to touch:**
  - `api/routes/search.py` — update `_parse_csv` or the kinds validation block in `search()` route
- **What to do:** In the `search()` route, when `parsed_kinds` is not `None` but is an empty list (which `_parse_csv` returns for `kinds=`), treat it the same as when all kinds are toggled off — return an empty results list rather than running the full search. This aligns backend behavior with the frontend's `allKindsOff` short-circuit.

  The cleanest fix: in `_parse_csv`, when the input is an empty string (not `None`), return `[]` (not `None`). Then in the route, when `parsed_kinds == []`, return early with empty results:

  ```python
  if parsed_kinds == []:
      return SearchResponse(query=q, results=[])
  ```

- **Test:** `GET /api/search?q=我想吃&kinds=` (empty value) should return `{"query":"我想吃","results":[]}` (same as frontend's all-kinds-off state). Currently it returns 5 results as if no filter was applied.
- **Dependencies:** none (P2, independent)
- **ponytail note:** The frontend already handles this correctly; the fix is purely to make the backend consistent.

---

### Step 7: Duplicate sentence deduplication (data fix)

- **Agent:** executor
- **Note:** This is a **data fix**, not a code fix. S5/S12 are both "我喜欢吃 (wǒ xǐ huān chī)" and S1/S31 are both "我流口水了 (wǒ liú kǒu shuǐ le)". The code is working correctly; the vault has duplicate entries.
- **What to do (if time permits):**
  1. Identify S5 vs S12 and S1 vs S31 — check `vault/units/sentences/` JSON files
  2. Merge or archive the duplicate (e.g., keep S5 and S12, update any connections pointing to S12 to point to S5, then delete S12)
  3. Verify no other references break
- **Test:** After dedup, re-run the search queries from the test session. Duplicates should no longer appear in results (S5 and S12 will collapse to one entry).
- **Dependencies:** Step 5 (containing_sentences fix makes it easier to identify which sentence is the canonical one by seeing which has more connections)

---

## Phase 4: QA Review (qa-reviewer)

- **Agent:** qa-reviewer
- **What:** Grade all fixes against the gap analysis from `.specs/functional-test-session.md`
- **Re-run the functional tests from the test session** (Test Groups A–D) against the fixed codebase:
  - A1: English query `i want to eat` — should now show semantic results mixed in (not just lexical)
  - A2: Pinyin query `wo xiang chi` — S9 should be at position 1 or 2, not 13
  - A3: Chinese query `我想吃` — should be unchanged (baseline)
  - B2: Semantic-only `semantic` query at default threshold — should now return results (not 0)
  - D4: Tone-marked pinyin `wǒ xiǎng chī` — S9 should be in top 3, no groups dominating results
  - D3: Long input 1000 chars — should return 422, not crash
  - C2: Word-only query — should show sentence context for word results
  - B5 / D1: Empty kinds filter — should return empty results from backend (not 5 results)
- **Pass criteria:** All P0 gaps resolved (semantic results appear, pinyin ranking corrects, tone-marked pinyin works). P1 gaps resolved or justified in writing (e.g., word context full implementation vs. minimal count-only).

---

## Phase 5: Refactor (refactor-cleaner)

- **Agent:** refactor-cleaner
- **What:** After all fixes land, check for:
  1. **Duplicate pinyin-normalization logic** — `_strip_diacritics` is now in `lexical.py` and imported by `search.py`. Ensure no duplicate copy exists elsewhere.
  2. **Dead threshold code** — if the default threshold changed, ensure no hardcoded `0.6` references in tests or documentation are now stale.
  3. **Unused imports** — `_strip_diacritics` in `search.py`, any new fields in schemas.
  4. **Redundant `kinds=` guard** — if Step 6 added an early-return for `parsed_kinds == []`, check whether the frontend's `allKindsOff` short-circuit is now redundant (it isn't — the frontend short-circuit prevents the network call, which is still valuable for UX).
  5. **`tokenize_sentence` comment** — the existing comment says "A future task can swap this for jieba segmentation." With pinyin normalization now in place, determine whether that jieba upgrade is still needed. If not, remove the comment to avoid misleading future maintainers.
  6. **`_score_unit` pinyin path** — verify the pinyin detection regex is correct and minimal.

---

## Summary

| Step | Fix | Branch | Files | Agent | Priority |
|------|-----|--------|-------|-------|----------|
| 1 | Tone-mark normalization | `fix/p0-tone-mark-normalization` | `lexical.py`, `search.py` | executor | P0 |
| 2 | Semantic threshold | `fix/p0-semantic-threshold` | `config.py` | executor | P0 |
| 3 | Pinyin ranking | `fix/p0-pinyin-ranking` | `search.py` | executor | P0 |
| 4 | Long input guard | `fix/p1-long-input-validation` | `routes/search.py` | executor | P1 |
| 5 | Word sentence context | `fix/p1-word-context` | `schemas.py`, `search.py`, `ResultRow.svelte`, `api.ts` | executor | P1 |
| 6 | `kinds=` empty string | `fix/p2-kinds-empty` | `routes/search.py` | executor | P2 |
| 7 | Duplicate deduplication | `fix/p2-dedup` | `vault/units/sentences/*.json` | executor | P2 |
| QA | Review | — | — | qa-reviewer | — |
| RC | Refactor | — | — | refactor-cleaner | — |

**Parallel execution:** Steps 1 and 2 are independent and can be executed in parallel. Step 3 depends on Step 1. Steps 4 and 5 are independent of P0 steps and each other. Steps 6 and 7 are P2 — implement only if time permits after QA passes.
