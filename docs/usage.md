# Usage — the learner tour

The app is built around a single loop: add a sentence, let the AI propose
labels, confirm and save, then search and organize.

## The loop in five steps

### 1. Add a sentence

Open `/add`. Enter hanzi — for example, `我喜欢吃饺子`. Optionally type an
English hint such as `I like to eat dumplings`. Click **Propose labels**.
The AI suggests pinyin, English meaning, word segmentation, and connections.

You can edit any field before saving.

### 2. Review and save

Click **Save**. The app creates a sentence unit and automatically creates
word units for each token the AI identified. It also links the sentence to
existing words that share hanzi or pinyin, and proposes group membership.

The save is synchronous — you see the new unit immediately.

### 3. Search

Return to `/` (the default search page). Type hanzi, pinyin, or English
meaning. Results appear below the fold as you type. Use the kind toggles
above the results to show or hide lexical and semantic matches. Use the
type filters (including "cmpd" for compound units) to narrow results.

### 4. Open a result

Click any result to open `/unit/{id}`. You see all the unit's properties
and connections grouped by kind (lexical, semantic, opposite, group). For
words, the page also lists every sentence that contains that word.

### 5. Organize

On a unit's detail page, add or remove connections. The AI can propose
new antonyms or group suggestions when you save — the app surfaces those
proposals and you confirm or reject them.

## UI routes

| Route | What it is |
|---|---|
| `/` | Default search page — search box above the fold, results below; "Browse vault" link beside "+ Add sentence" |
| `/add` | Add-sentence page — hanzi input, AI propose, all fields editable |
| `/unit/{id}` | Unit detail — properties, connections, containing sentences |
| `/vault` | Browse vault — list units by type (Word \| Compound \| Sentence) with sort and auto-pagination above 50 |

## API surface

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/sentences` | Propose labels (hanzi in, full proposed unit out, not saved) |
| `POST` | `/api/sentences/commit` | Save a confirmed sentence unit |
| `GET` | `/api/search?q=&kinds=&types=` | Search — returns ranked related units |
| `GET` | `/api/search/suggest?q=&limit=5` | Autocomplete — up to 5 unit names matching prefix |
| `GET` | `/api/meanings/{text}/sentences` | Semantic search by English meaning |
| `GET` | `/api/units/{id}` | Single unit with full properties |
| `POST` | `/api/reindex` | Full rebuild of `vault/index/` |
| `GET` | `/api/vault/list?type=&limit=&offset=&sort=` | Browse vault — returns `id`, `name`, `snippet` only (no `english`/`meaning`); auto-paginates above 50 |
| `GET` | `/healthz` | Health check (includes `mock_mode: true/false`) |

For the full technical spec, see
[.specs/language-brain.md §5.2](.specs/language-brain.md).
