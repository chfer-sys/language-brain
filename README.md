# Language Brain

A local-first web app in which you author a personal knowledge graph of
**Chinese language units** — sentences, words, and groups — and the app
surfaces the right related units when you type a meaning, a fragment, or
a full sentence you are trying to produce.

The full design lives in [`.specs/language-brain.md`](.specs/language-brain.md).

## Quick start

```bash
# 1. Install (editable, with dev deps)
pip install -e ".[dev]"

# 2. Configure your AI key (mock mode is the default if unset)
cp .env.example .env  # then edit .env
# LANGUAGE_BRAIN_AI_KEY=...
# LANGUAGE_BRAIN_AI_ENDPOINT=https://api.MiniMax.chat/v1
# LANGUAGE_BRAIN_AI_MODEL=M2.7

# 3. Run the API on http://localhost:8000
uvicorn api.main:app --reload

# 4. Run the frontend on http://localhost:5173
cd app && npm install && npm run dev
```

Then open <http://localhost:5173/>. The default page is a search box;
type hanzi, pinyin, or English meaning to see related units below the
fold. Click any result to open that unit's detail page. Click
**+ Add sentence** to author a new sentence.

## Environment

| Variable | Default | Notes |
|---|---|---|
| `LANGUAGE_BRAIN_VAULT` | `./vault/` | Filesystem path to the vault root. Override to relocate your data. |
| `LANGUAGE_BRAIN_AI_KEY` | unset (mock mode) | API key for the AI provider. **Never commit a real key.** |
| `LANGUAGE_BRAIN_AI_ENDPOINT` | `https://api.MiniMax.chat/v1` | AI provider base URL. |
| `LANGUAGE_BRAIN_AI_MODEL` | `M2.7` | Default model identifier. |
| `LANGUAGE_BRAIN_EMBEDDER` | auto (try real, fall back to hashing) | Set to `hashing` for a deterministic, model-free dev mode. Set to `real` to force `sentence-transformers`. |
| `HF_ENDPOINT` | `https://hf-mirror.com` (baked into the test image) | HuggingFace endpoint for the embedder model download. |
| `HF_HOME` | `/root/.cache/huggingface` (in the test image) | Local cache for HuggingFace model files. |

Secrets are loaded from `.env` via `python-dotenv` and are exposed as
`pydantic.SecretStr` so they never appear in logs, `repr()`, or JSON
dumps.

### Embedder modes

The default embedder is `sentence-transformers/all-MiniLM-L6-v2` (SPEC
§9). On first use it downloads ~80MB from HuggingFace. If your network
is slow or restricted:

- **Recommended**: set `HF_ENDPOINT=https://hf-mirror.com` (already
  baked into the test docker image) — the mirror is reachable from
  restricted networks and serves the same model.
- **Fallback**: set `LANGUAGE_BRAIN_EMBEDDER=hashing` to use a
  deterministic hash-based embedder with no model download. Semantic
  search degrades (no cosine similarity) but lexical search and the
  UI work normally.

## Pre-commit secret guard

`scripts/check_no_secrets.sh` greps tracked files for the `LANGUAGE_BRAIN_AI_KEY=`
assignment, common `sk-` style tokens, and `M2.7` followed by an
alphanumeric run. Wire it into git:

```bash
ln -s ../../scripts/check_no_secrets.sh .git/hooks/pre-commit
```

## Tests

```bash
# Backend (pytest)
docker run --rm --entrypoint="" \
    -v $(pwd):/work -w /work \
    opencode-language-brain-test \
    pytest tests/

# Frontend (vitest)
cd app && npm test
```

The current state: **438 pytest + 28 vitest, 0 failing**.

## UI routes

| Route | Purpose |
|---|---|
| `/` | Default page — search box above the fold (AC22). Results, kind-toggles, and type-filters render below the fold as you type. |
| `/add` | Add-sentence page — hanzi + optional English hint, "Propose labels" calls the AI, all 7 fields editable, "Save" commits to the vault. |
| `/unit/{id}` | Unit detail page — name, type, properties, connections grouped by kind. Word pages also list sentences containing the word (the word never renders alone). |

## API surface

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/sentences` | Propose labels (hanzi in, full proposed sentence unit out, no save). |
| `POST` | `/api/sentences/commit` | Save a confirmed sentence unit. Triggers word creation, group updates, index update. Synchronous — response returns only after all side effects complete (AC8b). |
| `GET` | `/api/search?q=&kinds=&types=` | Search. Returns ranked list of related units. **No `english`/`meaning` in payload.** |
| `GET` | `/api/search/suggest?q=&limit=5` | Autocomplete. Up to 5 unit names matching the prefix. No payload leak. |
| `GET` | `/api/meanings/{text}/sentences` | Given an English meaning, return sentence units whose `meaning` embedding has cosine > threshold (default 0.6). Only `id`, `hanzi`, `pinyin`, `score`. |
| `GET` | `/api/units/{id}` | Author view of a single unit (sentence / word / group). Includes `english`/`meaning`. Word responses additionally carry `containing_sentences`. |
| `POST` | `/api/reindex` | Full rebuild of `vault/index/`. |

The SvelteKit dev server (`localhost:5173`) and FastAPI (`localhost:8000`)
are cross-origin in dev, so the API runs a small `CORSMiddleware`
allowlist for `localhost:5173` and `localhost:4173`. In production the
frontend is served from the same origin and CORS is a no-op.

## Project layout

See [`.specs/language-brain.md` §5.1](.specs/language-brain.md) for the
canonical layout. The short version:

```
api/                          FastAPI backend (Python)
  routes/
    add_sentence.py           POST /api/sentences (propose)
    commit_sentence.py        POST /api/sentences/commit (save)
    search.py                 GET  /api/search + /search/suggest + /meanings/{text}/sentences
    units.py                  GET  /api/units/{id}
  services/                   ai_client, unit_writer, embedder, indexer, connector, ...
  schemas.py                  Pydantic request/response models
  config.py                   Settings (env-driven)
app/                          SvelteKit frontend (TypeScript + Svelte 5)
  src/
    routes/
      +page.svelte            Default search page (AC22, AC23, AC24)
      add/+page.svelte        Add-sentence page (AC25)
      unit/[id]/+page.svelte  Unit detail page (AC26, AC27)
    lib/
      api.ts                  Typed fetch wrapper for FastAPI
      components/             SearchBox, ResultRow, KindToggles, UnitTypeFilters, AddSentenceForm
  tests/                      Vitest
vault/                        Units and FAISS index (JSON files on disk)
scripts/                      reindex.py + utilities
tests/api/                    pytest
Dockerfile.test               opencode-language-brain-test image (Python 3.12 + all deps + torch + sentence-transformers + faiss-cpu)
```