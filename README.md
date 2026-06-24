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

# 3. Run the API
uvicorn api.main:app --reload

# 4. Run the frontend (T28 will fill this in)
cd app && npm install && npm run dev
```

## Environment

| Variable | Default | Notes |
|---|---|---|
| `LANGUAGE_BRAIN_VAULT` | `./vault/` | Filesystem path to the vault root. Override to relocate your data. |
| `LANGUAGE_BRAIN_AI_KEY` | unset (mock mode) | API key for the AI provider. **Never commit a real key.** |
| `LANGUAGE_BRAIN_AI_ENDPOINT` | `https://api.MiniMax.chat/v1` | AI provider base URL. |
| `LANGUAGE_BRAIN_AI_MODEL` | `M2.7` | Default model identifier. |

Secrets are loaded from `.env` via `python-dotenv` and are exposed as
`pydantic.SecretStr` so they never appear in logs, `repr()`, or JSON
dumps.

## Pre-commit secret guard

`scripts/check_no_secrets.sh` greps tracked files for the `LANGUAGE_BRAIN_AI_KEY=`
assignment, common `sk-` style tokens, and `M2.7` followed by an
alphanumeric run. Wire it into git:

```bash
ln -s ../../scripts/check_no_secrets.sh .git/hooks/pre-commit
```

## Tests

```bash
pytest                       # backend (pytest)
cd app && npm run test       # frontend (vitest) — added in T28
```

## Project layout

See [`.specs/language-brain.md` §5.1](.specs/language-brain.md) for the
canonical layout. The short version:

```
api/        FastAPI backend (Python)
app/        SvelteKit frontend (TypeScript)
vault/      Units and FAISS index
scripts/    Reindex + smoke scripts
tests/      pytest + vitest
```
