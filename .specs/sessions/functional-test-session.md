# Functional Test Session — Language Brain

**Status:** COMPLETE — raw findings + gap analysis filled in
**Date:** 2026-07-13
**Target:** `http://192.168.100.101:8000`
**Person conducting:** human (this document is the plan)
**Plan authored by:** plan agent

---

## 1. UX Principles for This App

These principles are synthesized from NNGroup usability heuristics (Nielsen, 1994; updated 2024) and observed patterns in agentic AI products (Cursor, Copilot, Claude, Linear AI). Each is scoped to the specific context of a Chinese-language learning search interface.

---

### P1. Show the AI's work, not just the result

**Principle:** The app computes four distinct connection kinds (lexical, semantic, group, opposite) and three unit types (sentence, word, group) behind the scenes. The results UI must make visible which computation produced each result.

**What this means for search:**
- Each result row must show which `kinds` matched (e.g., a badge, label, or icon for each active kind)
- Toggling off a kind must produce an immediately visible change — results that depended solely on that kind disappear
- If a result appears because of multiple kinds, all contributing kinds must be shown

**Why it matters here:** A Chinese learner searching `我想吃` needs to know whether a result appeared because it shares hanzi (lexical), shares meaning (semantic), is in the same group, or is an antonym. Without kind labels, the learner cannot calibrate trust or learn from the connections.

**Anti-pattern:** Showing results with a single score but no breakdown of why each result was retrieved.

---

### P2. Empty states teach, not just say "no results"

**Principle:** When a query returns zero results, the empty state must communicate *why* (plausible cause) and *what to try next* (actionable next step). It should not be a dead end.

**What this means for search:**
- An empty result after `xyzqw` should explain that no match was found and suggest trying Chinese characters, pinyin, or English
- An empty result after a pinyin query on a vault with no sentences should distinguish "nothing indexed yet" from "not found"
- Empty states should be scoped to the active filter combination (e.g., "No sentences found with `opposite` kind — try enabling `lexical`")

**Anti-pattern:** A blank white panel with no text or guidance.

---

### P3. Toggles are always in sync with results

**Principle:** The four kind toggles and three unit-type filters must always produce a results pane that is consistent with their combined state. Every result shown must be explainable by at least one active filter; every active filter must be demonstrably affecting the results (or there must be a visible "no results from this filter" signal).

**What this means for search:**
- Disabling all four kinds should show zero results (not all results)
- Enabling only `lexical` must produce results that are only lexically connected
- The UI must not show stale results from a previous filter state while the new filter is loading

**Anti-pattern:** Filter toggles that visually update but don't actually restrict the result set, or results that appear despite having no active kinds that could produce them.

---

### P4. Input modality parity

**Principle:** The learner can type English (`i want to eat`), bare pinyin (`wo xiang chi`), or Chinese characters (`我想吃`). All three must produce results that are useful and semantically coherent for a Chinese learner. The system should not signal that one modality is preferred or primary.

**What this means for search:**
- English queries must surface semantically related sentences even if no English text is stored in the vault (embedding-based lookup)
- Pinyin queries must tokenize and match against stored pinyin
- Chinese character queries must match against hanzi
- The result quality for a given query should be comparable across modalities (though not necessarily identical — lexical matching will naturally be stronger for Chinese input)

**Anti-pattern:** Treating English as the "real" query and pinyin/Chinese as second-class inputs that produce degraded results.

---

### P5. Results must be interpretable at a glance

**Principle:** A Chinese-language learner using this app must be able to look at a result row and immediately understand: what unit type it is, what language(s) it displays, and why it appeared. All display-relevant information must be in the result row itself — not hidden behind a click or tooltip.

**What this means for search:**
- The result row must show: name (hanzi or slug), type (word/sentence/group), snippet (pinyin for sentences/words; member count for groups)
- Type labels must be visible and unambiguous (not color-only coding)
- Kind badges/indicators must be visible without hovering
- Score (if shown) must have a human-readable context ("0.81" means nothing without knowing the scale)

**Anti-pattern:** Showing only a hanzi name with no type label, requiring a click to determine if a result is a word or sentence.

---

### P6. The vault is a learning tool — show sentence context for words

**Principle:** Words never appear alone in the data model (per SPEC §2.2: "word units never stand alone in the UI — every word-unit view shows the sentences that contain it"). In search results, a word result should carry enough context to be meaningful on its own, or the UI should make clear that clicking the word is required to understand it.

**What this means for search:**
- A word result row should show at minimum: the hanzi, the pinyin, and one example sentence containing it (or a signal that example sentences exist)
- If the word has no sentence context in the vault, this should be a visible empty-state signal

**Anti-pattern:** Showing a word result as a bare hanzi with no context, leaving the learner unable to verify whether the word is relevant.

---

### P7. Graceful degradation under unusual inputs

**Principle:** The app must handle gibberish, empty input, and overlong input gracefully — without crashes, without 500 errors, and without surprising the user. The behavior should be predictable and educational.

**What this means for search:**
- Empty search box: show the default state (no results pane, or a "type to search" prompt)
- Gibberish (`xyzqw`): return zero results with an appropriate message, not an error
- Very long input: truncate gracefully in the UI; the backend should either handle it or return a meaningful error
- Pinyin with tones (`wǒ xiǎng chī`): treat as equivalent to pinyin without tones, or explain the difference

**Anti-pattern:** Long input causing a horizontal scroll, an API 500 error, or a silent hang.

---

### P8. Loading state must be visible and non-alarming

**Principle:** Network requests take time. The user must always know the system is working on their query. Long-running requests must not look like the app has frozen.

**What this means for search:**
- A visible loading indicator appears within 100–200ms of typing (before the debounce settles)
- The loading indicator does not displace or flash the existing results until new results are ready
- When results arrive, the loading indicator disappears and is replaced by results — no "flickering" between old and new states

**Anti-pattern:** User types, waits 800ms with no feedback, then results appear with no indication they are fresh.

---

## 2. Test Environment

### URL
- **Backend API:** `http://192.168.100.101:8000`
- **Frontend (if tested):** Same IP on the frontend port (typically 5173 in dev)

### Prerequisites
- [ ] The app is running at the IP above (`docker run --rm` or the deployed service)
- [ ] The vault contains existing units — at minimum:
  - At least 3 sentences (some containing `吃`, `想`, `我`, `好`, `吃`)
  - At least 1 word unit
  - At least 1 group unit
  - At least 1 antonym pair
- [ ] You have access to the machine running the app to observe console errors if any

### Browser
- Chrome or Firefox — desktop, viewport ~1200px wide
- DevTools console open to the **Network** tab (to observe request/response shapes if needed)

### How to record findings
- Fill in each **Raw findings** section during the test session by observing the live UI
- Do not interpret or judge — copy what you see verbatim
- After all raw findings are collected, the Gap Analysis will be done collaboratively

---

## 3. Test Group A: Input Modalities (Baseline — All Filters On)

**Purpose:** Establish the baseline result set for three query modalities. All four kinds and all three unit types are ON. Observe how the system handles English, pinyin, and Chinese character input.

**Setup:** Ensure all toggles are in their default ON state:
- Kind toggles: `lexical` ON, `semantic` ON, `group` ON, `opposite` ON
- Unit type filters: `sentence` ON, `word` ON, `group` ON

---

### Test: A1 — English query

**Query:** `i want to eat`
**Filters:** All kinds ON, all unit types ON

**Raw findings:**
- Result count: 20
- Types present: sentence, word
- Kinds present: lexical ONLY (no semantic, no group, no opposite despite all being ON)
- Top 5 results:
  1. S9 — sentence — 我想吃 (wǒ xiǎng chī) — ['lexical'] — 0.400
  2. W32 — word — 想 (xiǎng) — ['lexical'] — 0.400
  3. C810 — word — 吃饭 (chī fàn) — ['lexical'] — 0.273
  4. C9 — word — 喜欢 (xǐ huān) — ['lexical'] — 0.273
  5. S12 — sentence — 我喜欢吃 (wǒ xǐ huān chī) — ['lexical'] — 0.273
- UI elements visible: (not directly observed via API curl; kind badges present in JSON as `['lexical']`)
- Loading indicator: (not testable via API curl)
- Empty state or error: No

**Observations (raw, no judgment):**
- English tokens match against English glosses in the dictionary. Results are relevant (我想吃 = "I want to eat" is the top result).
- ZERO semantic results appear despite semantic being ON — the default threshold (0.6) filters them all out. Max semantic score observed for this query is ~0.509 at threshold 0.0.

---

### Test: A2 — Pinyin without tones query

**Query:** `wo xiang chi`
**Filters:** All kinds ON, all unit types ON

**Raw findings:**
- Result count: 20
- Types present: sentence, word
- Kinds present: lexical ONLY
- Top 5 results:
  1. S27 — sentence — 只是我这个个人会有一点搞笑 — ['lexical'] — 0.091
  2. S10 — sentence — 我准考 — ['lexical'] — 0.071
  3. W4 — word — 我 — ['lexical'] — 0.071
  4. C1400 — word — 受不了 — ['lexical'] — 0.067
  5. C810 — word — 吃饭 — ['lexical'] — 0.067
- S9 我想吃 (the exact pinyin match) appears at position 13 with score 0.067
- UI elements visible: (not directly observed via API curl)
- Loading indicator: (not testable via API curl)
- Empty state or error: No

**Observations (raw, no judgment):**
- Poor ranking. The exact pinyin match (S9 我想吃, pinyin "wǒ xiǎng chī") is buried at position 13. Unrelated sentences like S27 outrank it.
- Pinyin tokenization matches individual syllables ("wo", "xiang", "chi") against pinyin fields but doesn't weight multi-syllable matches higher.

---

### Test: A3 — Chinese characters query

**Query:** `我想吃`
**Filters:** All kinds ON, all unit types ON

**Raw findings:**
- Result count: 20
- Types present: sentence, word
- Kinds present: lexical ONLY
- Top 5 results:
  1. S9 — sentence — 我想吃 (wǒ xiǎng chī) — ['lexical'] — 1.000
  2. S6 — sentence — 我吃饭 (wǒ chī fàn) — ['lexical'] — 0.500
  3. S12 — sentence — 我喜欢吃 (wǒ xǐ huān chī) — ['lexical'] — 0.400
  4. S5 — sentence — 我喜欢吃 (wǒ xǐ huān chī) — ['lexical'] — 0.400
  5. W174 — word — 吃 (chī) — ['lexical'] — 0.333
- UI elements visible: (not directly observed via API curl)
- Loading indicator: (not testable via API curl)
- Empty state or error: No

**Observations (raw, no judgment):**
- Excellent ranking. Exact match at score 1.0, followed by sentences sharing 2 of 3 characters. All lexical.
- No semantic results despite semantic being ON. Same threshold issue as A1.

---

## 4. Test Group B: Kind Filter Isolation (Fixed Query: `我想吃`)

**Purpose:** Verify that each kind toggle independently restricts results as expected. Use `我想吃` as the fixed query (it produced results in A3). Toggle kinds ONE AT A TIME — all other kinds must be OFF.

**Instruction:** For each test, turn OFF all kinds first, then turn ON only the one kind being tested.

---

### Test: B1 — Only `lexical` ON

**Query:** `我想吃`
**Filters:** `lexical` ON, `semantic` OFF, `group` OFF, `opposite` OFF; all unit types ON

**Raw findings:**
- Result count: 5+ (limited to 5 in display)
- Types present: sentence, word
- Kinds present (in results): ['lexical'] only — CORRECT
- Top 5 results:
  1. S9 — sentence — 我想吃 — 1.000
  2. S6 — sentence — 我吃饭 — 0.500
  3. S12 — sentence — 我喜欢吃 — 0.400
  4. S5 — sentence — 我喜欢吃 — 0.400
  5. W174 — word — 吃 (chī) — 0.333
- Does each result have a visible `lexical` badge/label?: API returns `['lexical']` in JSON — UI rendering not observed
- Are there any results that claim a kind other than `lexical`?: No — CORRECT

**Observations (raw, no judgment):**
- Lexical filter is working correctly. No other kinds present in results.

---

### Test: B2 — Only `semantic` ON

**Query:** `我想吃`
**Filters:** `lexical` OFF, `semantic` ON, `group` OFF, `opposite` OFF; all unit types ON

**Raw findings:**
- Result count: 0 at default threshold (0.6)
- At threshold=0.1: 5 results, scores 0.185–0.239
  - Top: S29 那你是什么专业啊 ("what's your major") — 0.239 — semantic
  - S23 你想吃广东本地特色美食吗 ("do you want to eat Cantonese food") — 0.185 — semantic
- Does each result have a visible `semantic` badge/label?: API returns `['semantic']` at threshold=0.1
- Are there any results that claim a kind other than `semantic`?: N/A at default threshold (zero results)

**Observations (raw, no judgment):**
- Semantic search IS functional but the default threshold (0.6) makes it produce ZERO results.
- The English all-MiniLM-L6-v2 model produces poor semantic matches for Chinese text — "what's your major" outranks "do you want to eat Cantonese food" for the query "我想吃".

---

### Test: B3 — Only `group` ON

**Query:** `我想吃`
**Filters:** `lexical` OFF, `semantic` OFF, `group` ON, `opposite` OFF; all unit types ON

**Raw findings:**
- Result count: 0
- Types present: N/A
- Kinds present (in results): N/A (no results)

**Observations (raw, no judgment):**
- No group connections exist for units matching 我想吃. Expected if no sentences/words related to "eating" have been assigned to groups.

---

### Test: B4 — Only `opposite` ON

**Query:** `我想吃`
**Filters:** `lexical` OFF, `semantic` OFF, `group` OFF, `opposite` ON; all unit types ON

**Raw findings:**
- Result count: 0
- Types present: N/A
- Kinds present (in results): N/A (no results)

**Observations (raw, no judgment):**
- No antonym relationships exist for units matching 我想吃. Expected — eating-related words rarely have antonyms.

---

### Test: B5 — All kinds OFF

**Query:** `我想吃`
**Filters:** `lexical` OFF, `semantic` OFF, `group` OFF, `opposite` OFF; all unit types ON

**Raw findings:**
- Result count: Backend returns 5 results (`kinds=` treated as "no filter"); frontend short-circuits to 0
- Is there an empty state message?: Frontend shows empty results without calling API
- Did the UI visibly react to all four being off?: Frontend short-circuits: `if (allKindsOff || allTypesOff) { results = []; return; }`

**Observations (raw, no judgment):**
- Backend: `kinds=` (empty string) returns 5 results — interpreted as "no filter" = all kinds.
- Frontend: correctly shows zero results by not calling the API.
- Mismatch between backend and frontend interpretation of "no kinds selected."

---

## 5. Test Group C: Unit Type Filter Isolation (Fixed Query: `我想吃`)

**Purpose:** Verify that each unit type filter independently restricts results. Use `我想吃` as the fixed query. Toggle unit types ONE AT A TIME — all other unit types must be OFF. All four kinds are ON.

---

### Test: C1 — Only `sentence` ON

**Query:** `我想吃`
**Filters:** All kinds ON; `sentence` ON, `word` OFF, `group` OFF

**Raw findings:**
- Result count: 5
- Types present (should only be `sentence`): all sentence — CORRECT
- Top 5 results:
  1. S9 — sentence — 我想吃 — 1.000
  2. S6 — sentence — 我吃饭 — 0.500
  3. S12 — sentence — 我喜欢吃 — 0.400
  4. S5 — sentence — 我喜欢吃 — 0.400
  5. S10 — sentence — 我准考 — 0.200
- Any `word` or `group` results mixed in?: No — CORRECT

**Observations (raw, no judgment):**
- Sentence filter is working correctly.

---

### Test: C2 — Only `word` ON

**Query:** `我想吃`
**Filters:** All kinds ON; `sentence` OFF, `word` ON, `group` OFF

**Raw findings:**
- Result count: 5
- Types present (should only be `word`): all word — CORRECT
- Top 5 results:
  1. W174 — word — 吃 (chī) — 0.333
  2. W32 — word — 想 (xiǎng) — 0.333
  3. W4 — word — 我 (wǒ) — 0.333
  4. C69937 — word — 我也 (wǒ yě) — 0.250
  5. C810 — word — 吃饭 (chī fàn) — 0.250
- Any `sentence` or `group` results mixed in?: No — CORRECT
- Do word results show context (sentence containing the word) or just the word?: Just the word — bare hanzi + pinyin only. No example sentence, no "contained in N sentences" indicator.

**Observations (raw, no judgment):**
- Word results show bare hanzi + pinyin only. NO sentence context. The word 吃 appears with just "chī" — no indication that 4+ sentences contain this word.

---

### Test: C3 — Only `group` ON

**Query:** `我想吃`
**Filters:** All kinds ON; `sentence` OFF, `word` OFF, `group` ON

**Raw findings:**
- Result count: 0
- Types present (should only be `group`): N/A (no results)
- Any `sentence` or `word` results mixed in?: N/A
- Do group results show member count or other group-specific info?: N/A

**Observations (raw, no judgment):**
- No group units match the query.

---

## 6. Test Group D: Edge Cases

**Purpose:** Verify graceful handling of unusual, invalid, and boundary inputs.

---

### Test: D1 — Empty search box

**Query:** (empty — clear the search box entirely)
**Filters:** All kinds ON, all unit types ON

**Raw findings:**
- What is visible in the results pane?: Frontend clears results without API call
- Is there a placeholder message?: No results pane shown
- Is the loading indicator visible?: No
- Any error displayed?: No

**Observations (raw, no judgment):**
- Expected behavior. Frontend short-circuits: `if (query.trim().length === 0) { results = []; return; }`

---

### Test: D2 — Gibberish query

**Query:** `xyzqw`
**Filters:** All kinds ON, all unit types ON

**Raw findings:**
- Result count: 0
- Is there an empty state message?: API returns clean `{"query":"xyzqw","results":[]}`
- Does it explain why no results were found?: No
- Any error or crash?: No

**Observations (raw, no judgment):**
- Backend handles gracefully. Frontend would show "No results for 'xyzqw'." — no guidance on what to try instead.

---

### Test: D3 — Very long input

**Query:** `我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我我 me me me me`
**Filters:** All kinds ON, all unit types ON

**Raw findings:**
- Result count: N/A (request failed)
- Any horizontal overflow / layout break?: N/A
- Error or 500 returned?: HTTP 400 (Bad Request)
- Any truncation in the input box?: N/A
- Empty state message if no results?: N/A — request rejected

**Observations (raw, no judgment):**
- Backend rejects long input with 400. Should truncate or return empty, not error.

---

### Test: D4 — Pinyin with tones

**Query:** `wǒ xiǎng chī`
**Filters:** All kinds ON, all unit types ON

**Raw findings:**
- Result count: 5
- Types present: group (top 3), sentence, word — unexpected
- Kinds present: lexical
- Top 5 results:
  1. "character" — group — 0.250
  2. "greetings" — group — 0.250
  3. "shopping" — group — 0.250
  4. S10 — sentence — 我准考 — 0.067
  5. W4 — word — 我 — 0.067
- Is the result set the same as, different from, or overlapping with `wo xiang chi` (Test A2)?: Different — D4 returns groups as top 3; A2 returned zero groups in top 5
- Is the result set the same as, different from, or overlapping with `我想吃` (Test A3)?: Completely different — A3 had S9 at #1 with 1.000; D4 does not return S9 at all

**Observations (raw, no judgment):**
- Tone-marked pinyin causes the tokenizer to behave unexpectedly. Returns group names instead of pinyin matches. Tone marks (ǒ, ǎ, ī) confuse the jieba tokenizer.
- S9 我想吃 does NOT appear in D4 results. Significant regression vs tone-less pinyin (A2).

---

## 7. Gap Analysis

*Completed after raw findings collection — 2026-07-13.*

### UX Principle Compliance Table

| # | Principle | Status | Evidence | Gap | Priority |
|---|-----------|--------|----------|-----|----------|
| P1 | Show the AI's work | PARTIAL | Kind badges present in API response but only `lexical` ever appears in practice. Semantic, group, opposite are effectively dead. | Semantic threshold (0.6) kills all non-lexical results. User sees no variety in connection types. | P0 |
| P2 | Empty states teach | PARTIAL | Gibberish returns clean empty array. Frontend shows "No results for X." But no guidance on what to try instead. | Empty state is a dead end — no suggestions, no explanation of WHY no results. | P1 |
| P3 | Toggles in sync | PASS (frontend) / PARTIAL (backend) | Frontend short-circuits all-kinds-off correctly. Backend treats `kinds=` as "all kinds." | Backend `kinds=` empty string interpreted as "no filter" instead of "no kinds." | P2 |
| P4 | Input modality parity | FAIL | English and Chinese produce good results. Pinyin without tones has terrible ranking (exact match at position 13). Pinyin with tones produces completely wrong results (groups instead of sentences). | Pinyin search ranking is broken. Tone-marked pinyin is more broken. Three input modalities have vastly different quality. | P0 |
| P5 | Interpretable at a glance | PARTIAL | Results show name, type, snippet (pinyin). But word results lack context. Scores like 0.273 are not human-readable. | Word results are bare hanzi+pinyin with no context. Scores have no explanation of scale. | P1 |
| P6 | Words in context | FAIL | Word-only results (C2) show bare hanzi (吃 — chī). No example sentences, no "contained in N sentences" indicator. Violates SPEC §2.2. | Word search results violate SPEC invariant that words never stand alone. | P1 |
| P7 | Graceful degradation | PARTIAL | Gibberish handled well. Empty input handled well. Long input (1000 chars) returns 400 error. Tone-marked pinyin produces wrong results. | 400 error on long input. Tone-marked pinyin tokenization is broken. | P1 |
| P8 | Loading state visible | N/A | Not testable via API curl. Requires browser observation. | Needs manual browser verification. | — |

### Functional Gaps (not UX principle-specific)

| Gap | Severity | Description |
|-----|----------|-------------|
| Semantic search effectively dead | P0 | Default threshold (0.6) filters out ALL semantic results. Max observed semantic score across all queries: 0.509. The semantic toggle appears to do nothing to the user. |
| Pinyin ranking broken | P0 | "wo xiang chi" returns S9 我想吃 at position 13/20 with score 0.067. Unrelated S27 outranks it at 0.091. Multi-syllable pinyin matching doesn't boost exact matches. |
| Tone-marked pinyin broken | P0 | "wǒ xiǎng chī" returns group units as top results instead of sentences. Tokenizer can't handle tone diacritics. S9 我想吃 missing entirely. |
| Long input crashes | P1 | 1000-char input returns HTTP 400. Should truncate or return empty, not error. |
| Duplicate sentences | P2 | S5 and S12 are both "我喜欢吃" with identical pinyin. S1 and S31 are both "我流口水了". Data quality issue — likely duplicate entries in vault. |
| English model for Chinese semantics | P1 | all-MiniLM-L6-v2 is English-focused. Chinese semantic matches are poor quality (0.239 for "what's your major" matching "我想吃"). A multilingual model would improve this. |

---

*End of test session. Raw findings collected via API curl against http://192.168.100.101:8000 on 2026-07-13.*
