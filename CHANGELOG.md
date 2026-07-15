# Changelog

All notable changes to Language Brain are documented here. Versions that
never shipped are omitted.

## [v0.7] — Vault by category browse (2026-07-15)

- New: `/vault` route — browse units by type (Word | Compound | Sentence) with sort and pagination above 50.
- New: `GET /api/vault/list?type=&limit=&offset=&sort=` — returns `id`, `name`, `snippet` only (no `english`/`meaning`).
- UI: home page surfaces `/vault` with a "Browse vault" link beside "+ Add sentence".
- UI: search type-filters gained a "cmpd" chip for compound units.

## v0.5.5 — Search parity and performance (2026-07-15)

Search quality and latency improvements with no API changes. A search parity
check confirms that results for representative queries match expectations.
Performance benchmarks are now runnable locally with
`python scripts/benchmark_search.py`.

For details, see [docs/release-notes/v0.5.5.md](docs/release-notes/v0.5.5.md).

## v0.5.4 — Antonym auto-mirror (2026-07-14)

Saving a word with an antonym now automatically updates the other word's
antonym list, keeping the relationship symmetrical. Previously antonyms were
one-directional only. The fix is transaction-safe.

See [.specs/versions/v0.5-storage-and-dict.md](.specs/versions/v0.5-storage-and-dict.md).

## v0.5.3 — Dictionary integration (2026-07-13)

Words and compounds now get their id, pinyin, and English gloss from the
SUBTLEX-CH dictionary (33k entries). New sentences automatically look up
each word in the dictionary. Existing units can be backfilled with
`python scripts/backfill_word_english.py`.

See [.specs/versions/v0.5-storage-and-dict.md](.specs/versions/v0.5-storage-and-dict.md).

## v0.5.2 — ID migration (2026-07-12)

All units received stable typed ids: `W{n}` for words, `C{n}` for compounds,
`S{n}` for sentences, `G{n}` for groups. Internal references were rewritten
across all units. The migration is idempotent — running it twice is a no-op.

See [.specs/versions/v0.5-storage-and-dict.md](.specs/versions/v0.5-storage-and-dict.md).

## v0.5.1 — Storage layer (2026-07-11)

The vault moved from JSON files on disk to SQLite (`vault/index/vault.db`)
with a git-tracked SQL dump mirror (`vault/index/vault.dump.sql`). The binary
database is gitignored. Every save produces a new dump, making history
reviewable and data restorable with one command.

See [.specs/versions/v0.5-storage-and-dict.md](.specs/versions/v0.5-storage-and-dict.md).

## v0.4 — Word auto-create, antonyms, orphan cleanup (2026-07-09)

Major milestone: the app now creates word units automatically when you save
a sentence. The AI proposes antonyms and group membership. Pre-existing
orphan word units (single characters from the old greedy segmentation) were
cleaned up.

See [.specs/versions/v0.5-bounded-tags-and-optional-ai.md](.specs/versions/v0.5-bounded-tags-and-optional-ai.md) (v0.4 features described there).
