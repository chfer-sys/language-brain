# Language Brain — Specification v0.3

**Status:** DRAFT — pending user sign-off
**Date:** 2026-06-24
**Supersedes:** `.specs/SPEC.v0.2.md` (preserved for history)
**Vault root (default):** `./vault/` inside this repo, overridable via `LANGUAGE_BRAIN_VAULT` env var

> v0.3 is a rewrite of v0.2 reflecting the 2026-06-24 brainstorming session. v0.2
> modeled a chat-log ingestion pipeline with an LLM confidence gate. v0.3
> drops that pipeline entirely and pivots to a search-first, author-driven
> knowledge graph.

---

## 1. Goal

Build a local-first web app in which the user authors a personal knowledge
graph of **Chinese language units** (sentences, words, and groups) and the
app's job is to surface the right related units when the user types a
meaning, a fragment, or a full sentence they're trying to produce.

### 1.1 Non-goals (MVP)

- No multi-user, no auth, no cloud sync, no hosted service.
- No chat-log ingestion, no automatic sentence segmentation, no
  batch extraction. The user authors one unit at a time.
- No LLM confidence scoring, no review queue, no `pending/` folder.
  The user is the only author; the AI only proposes labels.
- No spaced repetition, no flashcards, no quiz mode.
- No mobile-specific UI (desktop browser only for MVP).
- No external dictionary pulls (HSK, WordNet, CC-CEDICT) at runtime.
  The AI is the only source of group/antonym proposals.
- No markdown frontmatter. The canonical store is structured JSON.
  Markdown is an export-only view (out of scope for MVP).
- English is *still* a hidden semantic layer. It powers indexing but
  is never displayed in the result UI.

---

## 2. The Unit Model

A **unit** is a node in a typed graph. There are exactly three unit types:

| Type | Example | Atomic input? |
|---|---|---|
| `sentence` | `我流口水了` ("I'm drooling") | yes — primary input |
| `word` | `吃` ("eat") | no — always shown with the sentences that contain it |
| `group` | `basic-verbs` | no — a cluster of sentence and/or word units |

All three types share the same shape:

```json
{
  "id": "<stable id>",
  "type": "sentence | word | group",
  "name": "<display name — hanzi for sentence/word, slug for group>",
  "properties": { ... type-specific ... },
  "connections": [
    { "to": "<unit id>", "kind": "lexical | semantic | group | opposite", "score": <float> }
  ],
  "created": "<ISO date>",
  "updated": "<ISO date>",
  "author_confirmed": true
}
```

### 2.1 Sentence unit

Authored by the user. AI proposes properties at add time; user edits
before saving.

```json
{
  "id": "2026-06-24-001",
  "type": "sentence",
  "name": "我流口水了",
  "properties": {
    "hanzi": "我流口水了",
    "pinyin": "wǒ liú kǒu shuǐ le",
    "english": "I'm drooling",
    "meaning": "I see food and my mouth waters; visual craving",
    "words": ["我", "流", "口水", "了"],
    "word_refs": ["wǒ", "liú", "kǒushuǐ", "le"],
    "groups": ["reactions", "food"],
    "antonyms": []
  },
  "connections": [
    { "to": "看起来很好吃", "kind": "semantic", "score": 0.81 },
    { "to": "reactions",    "kind": "group",    "score": 1.0 }
  ],
  "created": "2026-06-24",
  "updated": "2026-06-24",
  "author_confirmed": true
}
```

### 2.2 Word unit

Derived from sentences. A word unit is created the first time a hanzi
token appears in a confirmed sentence. **Word units never stand alone
in the UI** — every word-unit view shows the sentences that contain it.

```json
{
  "id": "chi",
  "type": "word",
  "name": "吃",
  "properties": {
    "hanzi": "吃",
    "pinyin": "chī",
    "english": "to eat",
    "meaning": "the act of eating, consuming food",
    "groups": ["basic-verbs", "food"],
    "antonyms": ["饿"]
  },
  "connections": [
    { "to": "喝",  "kind": "group",    "score": 1.0 },
    { "to": "饿",  "kind": "opposite", "score": 1.0 },
    { "to": "2026-06-24-001", "kind": "lexical", "score": 1.0 }
  ],
  "created": "2026-06-24",
  "updated": "2026-06-24",
  "author_confirmed": true
}
```

### 2.3 Group unit

A user- or AI-proposed cluster. Viewable as a node; groups contain
sentence and/or word unit references.

```json
{
  "id": "basic-verbs",
  "type": "group",
  "name": "basic-verbs",
  "properties": {
    "display_name": "Basic Verbs",
    "description": "Common everyday actions",
    "members": ["chi", "he", "shui", "zou"]
  },
  "connections": [
    { "to": "food",      "kind": "group", "score": 0.6 },
    { "to": "daily-life","kind": "group", "score": 0.8 }
  ],
  "created": "2026-06-24",
  "updated": "2026-06-24",
  "author_confirmed": true
}
```

### 2.4 Connections — the four link kinds

Every unit has a list of outgoing connections. Each connection has a
`kind` drawn from this fixed set:

| Kind | Definition | How it's computed |
|---|---|---|
| `lexical` | Shares a hanzi or pinyin token with the target. | Deterministic substring match on the `hanzi`/`pinyin` fields of the source and target sentence/word units. Score = Jaccard over token sets. |
| `semantic` | English meaning is similar. | Cosine similarity over `meaning` (preferred) or `english` (fallback) embeddings, computed via a local sentence-transformers model. Score = cosine. |
| `group` | Belongs to the same group unit. | Membership lookup. Score = 1.0 if both source and target are members of the same group, 0.0 otherwise. |
| `opposite` | Declared antonym. | Stored explicitly on the source unit. Score = 1.0. |

**Connections are materialized on the unit file**, not computed at query
time. When a unit is added/edited, the connection-update script:

1. Computes lexical and semantic edges to every other unit (or every
   unit in the same partition — TBD optimization).
2. Reads declared `group` and `opposite` edges from the source's
   properties.
3. Writes the top-N connections per kind to the unit file
   (N is a tunable; default 20 per kind).

This makes the data inspectable on disk and keeps queries a simple
union over already-materialized edges.

### 2.5 On-disk layout

```
vault/
  units/
    sentences/2026-06-24-001.json
    sentences/2026-06-24-002.json
    words/chi.json
    words/he.json
    groups/basic-verbs.json
    groups/food.json
  index/
    embeddings.npy        # sentence-transformers output, keyed by unit id
    faiss.index           # FAISS index over the embeddings
    unit_index.json       # id -> path lookup
  app/                    # SvelteKit frontend (sibling to vault, NOT inside it)
  api/                    # FastAPI backend
  scripts/                # reindex.py, new-unit.py, etc.
  README.md
```

The vault root is configurable via the `LANGUAGE_BRAIN_VAULT` env var.
Default in dev is `./vault/`. In production (out of MVP scope) the
user can point it at `/vault/projects/language-brain/` or any other path.

---

## 3. User Journey

### 3.1 Add a sentence (the primary input)

1. User opens the app. Default view is the search box.
2. User clicks **+ Add sentence**.
3. A modal opens. User types hanzi in one field, optionally a quick
   note in English.
4. User clicks **Propose labels**.
5. The AI proposes: `pinyin`, `english`, `meaning` (richer gloss),
   `words[]` (segmentation), `word_refs[]`, `groups[]` candidates,
   `antonyms[]` candidates.
6. User reviews each proposed field. They can edit, accept, or
   override.
7. User clicks **Save**.
8. The system:
   - Writes the sentence unit file to `vault/units/sentences/`.
   - Creates or updates any newly-seen word units under `vault/units/words/`.
   - Adds the sentence to any proposed groups.
   - Runs the connection-update script (lexical + semantic edges
     recomputed; group/opposite edges written).
   - Updates `vault/index/embeddings.npy` and `faiss.index`.

### 3.2 Search (the primary output)

1. User types into the search box. Typing is incremental.
2. The query can be:
   - Broken pinyin: `kanqila hao chi`
   - Broken hanzi: `看起来好吃`
   - English meaning fragment: `looks delicious`
   - A group name: `basic-verbs`
3. The system tokenizes the query, identifies the probable unit type
   being asked about (sentence, word, or group), and runs the four
   link-kind searches in parallel.
4. The result pane shows related units, ranked and merged.
5. Four **kind-toggles** sit at the top of the pane:
   `[lexical]  [semantic]  [group]  [opposite]`
   Each is on by default; user can disable any.
6. Three **unit-type filters** sit beside them:
   `[sentences]  [words]  [groups]`
   Each is on by default.
7. Clicking any result opens that unit's detail view.

### 3.3 View a word

- Word unit page is a list of all sentences containing that word,
  plus the word's groups, antonyms, and semantically-related words.
- The word never appears alone — always in context of its sentences.

### 3.4 View a group

- Group page shows all member sentence and word units, with a brief
  description. Useful for "what kind of things appear in my daily
  life" browsing.

### 3.5 Edit / delete a unit

- Every unit has an edit and delete action on its detail page.
- Editing re-runs the connection-update script.
- Deleting removes the unit file, removes it from any group members,
  and removes its connections from other units' connection lists.

---

## 4. Requirements

### 4.1 Functional

- **R1.** User can add a sentence by typing hanzi, optionally an
  English note, and clicking "Propose labels."
- **R2.** AI proposes pinyin, english, meaning gloss, words,
  candidate groups, and candidate antonyms in a single response.
- **R3.** User can edit any proposed field before saving.
- **R4.** On save, a sentence unit file is written under
  `vault/units/sentences/`.
- **R5.** On save, any unseen word in the sentence creates a word
  unit under `vault/units/words/`. Existing words are updated with
  the new sentence reference.
- **R6.** On save, the sentence is added to the members of every
  proposed group. New groups are created if a proposed group name
  does not exist.
- **R7.** On save, the connection-update script recomputes the new
  unit's lexical and semantic edges and writes the top-N to its file.
  For existing units, only edges involving the new/changed unit are
  recomputed (incremental).
- **R8.** On save, the embedding index is updated incrementally
  (one vector added to `faiss.index`).
- **R9.** User can search by typing in the search box. Query runs
  incrementally (debounced 200ms).
- **R10.** Search results are the union of the four link-kind
  searches, with kind-toggles defaulting to all on.
- **R11.** Result pane has three unit-type filters (sentences,
  words, groups) defaulting to all on.
- **R12.** Each result row shows: unit name (hanzi for sentence/word,
  slug for group), unit type, a snippet (pinyin for sentence, english
  gloss for word, member count for group), the connection kind(s)
  that matched, and a score.
- **R13.** **English is never displayed in the result UI.** The
  `english` and `meaning` fields power indexing but are not rendered.
  Pinyin and hanzi are the only languages shown.
- **R14.** Clicking a result opens that unit's detail page.
- **R15.** Sentence detail page shows: hanzi, pinyin, meaning
  (English shown here, this is the author view, not the search
  results UI), word list, group list, connections grouped by kind.
- **R16.** Word detail page shows: hanzi, pinyin, english, groups,
  antonyms, the full list of sentences containing this word.
- **R17.** Group detail page shows: display name, description, member
  sentence and word units.
- **R18.** User can edit any unit from its detail page. Saving an
  edit re-runs the connection-update for that unit.
- **R19.** User can delete any unit. Delete cascades: removes the
  unit from any group, removes the unit's id from any connection
  lists of other units, removes the embedding from the FAISS index.
- **R20.** All data is stored in the local vault. No outbound network
  call except to the configured LLM API endpoint.

### 4.2 Non-functional

- **N1.** Runs entirely on a single developer machine.
- **N2.** Cold start to first usable search: < 5 seconds for a vault
  of up to 1000 units.
- **N3.** Search response: < 200ms for vaults up to 1000 units.
- **N4.** The vault directory is plain files; readable without the
  app. JSON files are pretty-printed.
- **N5.** All LLM calls go through one client module. Mocking the
  client must be possible for tests.
- **N6.** Connection-update script is idempotent — re-running it
  produces the same connections.

---

## 5. Exact Changes

This section enumerates the files and modules to be created. It is
the contract the coder agent works from.

### 5.1 Repository layout

```
language-brain/
  .specs/
    language-brain.md           # this file
    SPEC.v0.2.md                # historical
    _traces.md                  # populated in Phase 6
  vault/                        # default vault root
    units/
    index/
  api/                          # FastAPI backend
    app.py                      # FastAPI app entry
    routes/
      add_sentence.py
      search.py
      units.py
    services/
      ai_client.py              # MiniMax wrapper, mockable
      unit_writer.py            # writes/reads unit files
      segmenter.py              # jieba wrapper
      pinyin_gen.py             # pypinyin wrapper
      embedder.py               # sentence-transformers wrapper
      indexer.py                # FAISS + npy management
      connector.py              # connection-update logic
    schemas.py                  # pydantic models
    config.py                   # env, paths
    main.py
  app/                          # SvelteKit frontend
    src/
      routes/
        +page.svelte            # search box, the main screen
        add/+page.svelte        # add-sentence modal page
        unit/[id]/+page.svelte  # unit detail page
        group/[id]/+page.svelte # group detail page
      lib/
        api.ts                  # fetch wrappers
        components/
          SearchBox.svelte
          ResultRow.svelte
          KindToggles.svelte
          UnitTypeFilters.svelte
          AddSentenceForm.svelte
    svelte.config.js
    vite.config.ts
  scripts/
    reindex.py                  # full rebuild of index from vault
    new_unit_smoke.py           # CLI: add one sentence, useful for testing
  tests/
    api/                        # pytest
      test_unit_writer.py
      test_search.py
      test_connector.py
      test_invariant_no_english_in_results.py
      test_invariant_round_trip.py
    app/                        # Vitest
      result_renders_no_english.test.ts
      toggles_filter_correctly.test.ts
  pyproject.toml
  package.json
  README.md
```

### 5.2 API surface (FastAPI)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/sentences` | Propose labels (hanzi in, full proposed sentence unit out, no save). |
| `POST` | `/api/sentences/commit` | Save a confirmed sentence unit. Triggers word creation, group updates, index update. |
| `POST` | `/api/sentences/{id}` | Edit a sentence unit. Re-runs connection-update. |
| `DELETE` | `/api/sentences/{id}` | Delete a sentence unit. Cascades. |
| `GET` | `/api/search?q=...&kinds=...&types=...` | Search. Returns ranked list of related units. **No `english`/`meaning` in payload.** |
| `GET` | `/api/search/suggest?q=...&limit=5` | Autocomplete. Returns up to N unit names matching the prefix. No payload leak of `english`/`meaning`. |
| `GET` | `/api/meanings/{text}/sentences` | Given an English meaning fragment, return all sentence units whose `meaning` field is semantically similar (FAISS cosine > threshold). Returns sentence units, no `english`/`meaning` in payload — only `hanzi` and `pinyin` are exposed, plus id and score. |
| `GET` | `/api/units/{id}` | Get a single unit (author view, may include english/meaning). |
| `GET` | `/api/groups` | List all groups (for the "view by group" browse). |
| `GET` | `/api/groups/{id}` | Group detail. |
| `POST` | `/api/groups` | Create a group. |
| `POST` | `/api/reindex` | Full rebuild of `vault/index/`. |

### 5.3 Search response shape

```json
{
  "query": "看起来好吃",
  "results": [
    {
      "id": "2026-06-24-001",
      "type": "sentence",
      "name": "我流口水了",
      "snippet": "wǒ liú kǒu shuǐ le",
      "kinds": ["semantic", "group"],
      "score": 0.81
    }
  ]
}
```

**Invariant:** the response payload must never contain keys named
`english`, `meaning`, or any other natural-language gloss. Only `name`
(hanzi/slug) and `snippet` (pinyin or display-only text) are allowed.

### 5.4 Dependencies

- **Backend (Python):** `fastapi`, `uvicorn`, `pydantic`, `jieba`,
  `pypinyin`, `sentence-transformers`, `faiss-cpu`, `numpy`, `pytest`.
- **Frontend (Node):** `@sveltejs/kit`, `vite`, `typescript`, `vitest`,
  `@testing-library/svelte`.
- **AI provider:** MiniMax API (configurable endpoint + key via env).
  Model: M2.7 or M3.
- **Embeddings model:** `sentence-transformers/all-MiniLM-L6-v2`.
  English-only is fine because the embedded text is the English
  `meaning` gloss.

### 5.5 Configuration

Env vars (all read by `api/config.py`):

- `LANGUAGE_BRAIN_VAULT` — vault root path. Default `./vault/`.
- `LANGUAGE_BRAIN_AI_ENDPOINT` — MiniMax API URL.
- `LANGUAGE_BRAIN_AI_KEY` — API key. Read via `secret_read`; never
  baked in.
- `LANGUAGE_BRAIN_AI_MODEL` — `M2.7` or `M3`. Default `M2.7`.
- `LANGUAGE_BRAIN_CONNECTIONS_TOP_N` — default `20`.

---

## 6. Acceptance Checklist

This is the spine for Phase 4 (VERIFY). Each item is a discrete,
testable property.

### Vault & data layer

- [ ] **AC1.** Given a sentence unit JSON, writing it to
  `vault/units/sentences/{id}.json` and reading it back yields an
  equal object (deep equal, ignoring `updated` timestamp).
- [ ] **AC2.** A new word not seen before is created under
  `vault/units/words/{pinyin-with-tones}.json` (e.g. `chī.json`)
  when its first containing sentence is saved. The id is the
  tone-marked pinyin. A compound like `口水` is one word unit
  with id `kǒushuǐ.json`.
- [ ] **AC3.** An existing word's `connections` list is updated to
  include a `lexical` edge to a newly-saved sentence that contains it.
- [ ] **AC4.** Saving a sentence to a proposed group adds the
  sentence's id to that group's `members` array.
- [ ] **AC5.** A proposed group name that does not exist creates a
  new group unit file with that name as id.

### AI labeling

- [ ] **AC6.** Posting a hanzi sentence to `POST /api/sentences`
  returns a response with all of: `pinyin`, `english`, `meaning`,
  `words[]`, `word_refs[]`, `groups[]`, `antonyms[]` populated
  (using a mocked AI client in tests).
- [ ] **AC7.** The `meaning` field is a richer English gloss than
  the `english` field. The mock client returns distinct strings for
  the two and a test asserts `meaning != english`.
- [ ] **AC8.** All AI calls go through `services/ai_client.py`. A
  test that monkey-patches that module's `propose_labels` is the
  only way tests interact with the LLM.
- [ ] **AC8b.** `POST /api/sentences/commit` is synchronous. The
  response is not returned until the unit file is written, word
  units are created/updated, group memberships are updated, the
  connection-update script has run, and the FAISS index has been
  updated. Test asserts that all of these side effects are present
  by the time the HTTP response returns.

### Index

- [ ] **AC9.** After saving a sentence, the FAISS index contains one
  more vector, and the new vector's nearest neighbor by cosine
  similarity is itself (or another unit sharing its group).
- [ ] **AC10.** `scripts/reindex.py` running on a populated vault
  reproduces the same `faiss.index` and `embeddings.npy` byte-for-
  byte (idempotent).
- [ ] **AC11.** Deleting a sentence removes its vector from the
  FAISS index and removes its id from the connection lists of
  every other unit.

### Connections

- [ ] **AC12.** A `lexical` connection exists between two sentence
  units that share at least one hanzi token.
- [ ] **AC13.** A `semantic` connection exists between two sentence
  units whose `meaning` fields have cosine similarity > 0.6
  (threshold tunable).
- [ ] **AC14.** A `group` connection exists between two units that
  share group membership.
- [ ] **AC15.** An `opposite` connection exists when a unit's
  `antonyms` array references the target's id. The opposite edge
  is written symmetrically: saving `chi.antonyms = ["è"]` also
  writes `è.antonyms = ["chi"]` and adds the `opposite` connection
  on both units.

### Search

- [ ] **AC16.** Searching for a hanzi query returns at least the
  sentence units that contain any of the query tokens, ranked
  by Jaccard similarity.
- [ ] **AC17.** Searching for an English meaning query returns
  sentence units whose `meaning` embeddings have cosine > 0.6 to
  the query's embedding, ranked by similarity.
- [ ] **AC18.** Disabling the `semantic` toggle removes all
  `semantic`-kind results from the response.
- [ ] **AC19.** Disabling the `words` unit-type filter removes all
  word units from the response.
- [ ] **AC20.** Search response payload contains no `english` or
  `meaning` key, for any query, against any vault state.
- [ ] **AC21.** Search response payload contains no natural-
  language English text in any `name` or `snippet` field (assert
  the strings contain no ASCII a-z sequences of length >= 3,
  excluding pinyin's tone-marked vowels).

### UI

- [ ] **AC22.** The default page (`/`) renders a search box and
  no other content above the fold.
- [ ] **AC23.** Typing into the search box updates the result
  pane within 200ms of the user pausing (debounce).
- [ ] **AC24.** The four kind-toggles and three unit-type filters
  are visible and clickable. Each click updates the result pane
  without a page reload.
- [ ] **AC25.** The add-sentence page (`/add`) shows a hanzi
  textarea, an optional English note, a "Propose labels" button,
  and after the AI responds, editable fields for pinyin, english,
  meaning, words, groups, antonyms, and a "Save" button.
- [ ] **AC26.** A unit detail page (`/unit/{id}`) shows the unit's
  name, type, properties, and connections grouped by kind.
- [ ] **AC27.** A word detail page shows the word's properties
  AND every sentence unit whose `words` list contains this word's
  hanzi. The word never renders alone.
- [ ] **AC27b.** `GET /api/search/suggest?q=...&limit=5` returns
  at most 5 unit names matching the query as a prefix (case-
  insensitive hanzi/pinyin). Response payload contains no
  `english` or `meaning` field. The order is alphabetical for
  MVP (no ranking beyond that).
- [ ] **AC27c.** `GET /api/meanings/{text}/sentences` returns all
  sentence units whose `meaning` embedding has cosine similarity
  to the query's embedding above a configurable threshold
  (default 0.6). Response payload contains only `id`, `hanzi`,
  `pinyin`, and `score` per result. No `english` or `meaning`
  field in payload. The query itself is English and is *not*
  stored; it is embedded in-memory and discarded after the
  request.

### Operational

- [ ] **AC28.** `LANGUAGE_BRAIN_VAULT` env var changes the vault
  root. Test by running with two different values and asserting
  files are created in the right place.
- [ ] **AC29.** No outbound network calls happen during search,
  unit read, or unit write. Only the AI client (mocked in tests)
  makes network calls. Assertable via a request-blocker in tests.
- [ ] **AC30.** All AI calls in production use `secret_read` for
  the API key; the key string is never present in any source
  file, test fixture, or log output.

---

## 7. Out of Scope (Post-MVP)

- Multi-user, auth, cloud sync, hosting.
- Chat-log ingestion, batch import, automatic segmentation.
- Spaced repetition, flashcards, quiz mode.
- Mobile-specific UI.
- External dictionary pulls at runtime.
- Markdown as canonical store (markdown export is a possible
  future feature, not MVP).
- Cross-device sync, public API, collaborative editing.
- Advanced graph analytics, graph visualization, force-directed
  layouts.
- Multiple target languages.
- Confidence scoring, review queues, auto-accept thresholds.
- **Offline authoring.** For MVP, the AI label-proposal step
  requires network. If the user is offline, they hand-label
  (pinyin, english, meaning, groups, antonyms) themselves. A
  future post-MVP feature is to cache AI labels per sentence or
  per word, and a "Re-ask AI" flow that diffs the AI's new
  proposal against the offline-saved labels. Locked 2026-06-24.

---

## 8. Open Questions

These are decisions still pending. Each must be resolved before the
relevant task in Phase 2 can be planned by the coder.

- [x] **OQ1.** **Symmetric antonyms.** Saving a→b writes b→a. Locked 2026-06-24.
- [x] **OQ2.** **Pinyin-with-tones as the word id.** `word_refs[]`
  uses tone-marked pinyin (e.g. `chī`, `wǒ`). The `id` of a word
  unit is its tone-marked pinyin. Locked 2026-06-24.
- [x] **OQ3.** **One word per contiguous jieba token.** Compound
  hanzi like `口水` is one word unit. Locked 2026-06-24.
- [x] **OQ4.** **Synchronous connection-update.** `POST
  /api/sentences/commit` blocks until the connection-update
  script and the FAISS update complete. Returns only when the unit
  is fully indexed. Locked 2026-06-24.
- [x] **OQ5.** **Slugs as ids.** `id` is slug (`basic-verbs`),
  `display_name` is the human form (`Basic Verbs`). Locked
  2026-06-24.
- [x] **OQ6.** **200ms debounce.** Confirmed 2026-06-24.
- [x] **OQ7.** **Embeddings model: `all-MiniLM-L6-v2`.** 80MB
  local download on first run, then cached. App is offline-
  capable for all operations except AI label proposal. Locked
  2026-06-24.
- [x] **OQ8.** **Search autocomplete from unit names, top 5.**
  New endpoint: `GET /api/search/suggest?q=...&limit=5`. Locked
  2026-06-24.

---

## 9. Tech Stack (locked for v0.3)

| Layer | Choice | Why |
|---|---|---|
| Frontend | **SvelteKit + TypeScript** | Solo dev velocity, small bundle, FastAPI behind it works cleanly. |
| Backend | **Python FastAPI** | Async, typed, good for the kind of internal API surface we have. |
| AI provider | **MiniMax API (M2.7 default)** | Per user preference. |
| Embeddings | **sentence-transformers / all-MiniLM-L6-v2** | Local, free, 80MB, English-only is fine because we embed the English `meaning` gloss. |
| Vector index | **FAISS (faiss-cpu)** | Local, no service, fast for k-NN at small scale. |
| Segmentation | **jieba-py** | Standard for Chinese. |
| Pinyin | **pypinyin** | Standard, tone-aware. |
| Unit store | **JSON files on disk** | One file per unit, pretty-printed, greppable, durable. |
| Tests | **pytest** (backend) + **Vitest** (frontend) | Standard. |

**Explicitly NOT:** markdown frontmatter as canonical, Langflow,
Pinecone/Chroma as a service, Docker for the app itself, cloud DB,
auth/OAuth, external dictionary services.

---

## 10. Test Plan

Each acceptance checklist item has at least one test. Tests are
grouped by layer.

### 10.1 Backend (pytest)

- `test_unit_writer.py` — AC1, AC4, AC5, AC11
- `test_segmenter_and_pinyin.py` — OQ2, OQ3 setup
- `test_ai_client.py` — AC8 (monkey-patch contract)
- `test_add_sentence.py` — AC2, AC3, AC6, AC7
- `test_connector.py` — AC12, AC13, AC14, AC15
- `test_indexer.py` — AC9, AC10, AC11
- `test_search.py` — AC16, AC17, AC18, AC19, AC20, AC21, AC29
- `test_invariants.py` — AC20, AC21, AC29, AC30
- `test_config.py` — AC28

### 10.2 Frontend (Vitest)

- `result_renders_no_english.test.ts` — AC20, AC21 (UI side)
- `toggles_filter_correctly.test.ts` — AC18, AC19, AC24
- `add_sentence_form.test.ts` — AC25
- `unit_detail.test.ts` — AC26, AC27
- `search_debounce.test.ts` — AC23

### 10.3 E2E (manual for MVP, automated later)

- AC22 (default page is search box)
- AC27 visual check (word never renders alone)

---

## 11. Definition of Done

The MVP is done when:

1. All 30 acceptance checklist items pass.
2. The `qa-reviewer` agent has graded the build pass against this SPEC.
3. The `security-auditor` agent has graded the build pass.
4. The `docs-writer` agent has updated `README.md` and any inline
   docs to reflect v0.3 reality.
5. A trace record has been written to `.specs/_traces.md` per
   Phase 6.
6. The user has signed off on the final state.

---

## Changelog

- **v0.3.1 (2026-06-24):** Locked all 8 open questions. Symmetric
  antonyms. Pinyin-with-tones as word id. One word per jieba
  token. Synchronous commit. Slugs as group ids. 200ms debounce.
  `all-MiniLM-L6-v2` confirmed (offline-capable). Autocomplete
  endpoint added.
- **v0.3 (2026-06-24):** Major rewrite. Dropped chat-log ingestion
  and review queue. Pivoted to a search-first, author-driven typed
  graph with three unit types (sentence, word, group). Materialized
  connections. SvelteKit locked. FAISS for k-NN. AI is propose-
  only, user is author. English hidden in results, shown in
  author view.
- **v0.2 (2026-06-21):** Sentence-first model, hidden English,
  flagged-only review queue, dual search engine, web app + Obsidian
  vault. Preserved at `SPEC.v0.2.md`.
- **v0.1 (2026-06-21):** Initial spec. Word-first, Langflow planned.
