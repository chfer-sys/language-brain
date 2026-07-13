# Language Brain — Specification

**Version:** 0.2
**Date:** 2026-06-21
**Status:** DRAFT
**Vault path:** `/vault/projects/language-brain/`

> Distilled from the 2026-06-21 grill session. Supersedes v0.1.

---

## 1. Problem Statement

Language learners accumulate passive recognition (vocab apps, immersion) but struggle with **active production** — knowing what to say, not just recognizing what's said. A learner's knowledge is also **fragmented across tools** (Anki, notes, message logs) and **invisible to them** — they don't know which domains (business, food, transport) are weak, so they can't target practice.

Existing tools model *forms* (the word 吃, the phrase "to eat"). They do not model the *meaning* the learner is trying to express.

---

## 2. Solution

Language Brain is a personal knowledge base that captures **sentences the learner has acquired** and derives the words inside them as **connections**, not as the primary object. A sentence is the cell; words are the threads between cells.

The user thinks in their target language (Chinese). **English is a hidden semantic layer** — it powers search indexing but is never displayed. When the user searches, results are **hanzi + pinyin only**.

The product is a **browser web app** that reads/writes an **Obsidian vault as the data store** (markdown files + a graph index). Graph view is **secondary** to the main search/lookup UX.

---

## 3. User Stories

**Capture & ingestion**
1. Paste a chat log → AI extracts sentences I've encountered
2. AI proposes Meaning Units for review
3. AI flags only uncertain extractions (short, high-signal queue)
4. Flagged item shows *why* it was flagged
5. Approve / edit / reject in one click

**Core lookup loop**
6. Type a meaning in **English** → system finds sentences I have
7. Search results show **hanzi + pinyin only** (no English)
8. Confidence score on each result
 (1/5)
9. See sentence in context (other sentences sharing words)

**Search mechanics**
10. **Semantic search** (matches the idea)
11. **Lexical search** (exact hanzi/pinyin)
12. Both merged and re-ranked

**Browsing & structure**
13. **Tabular search view** as main screen
14. **Graph view** as secondary tool
15. Click a word → see all sentences containing it

**Coverage & feedback**
16. Coverage dashboard (% per domain)
17. Weekly acquisition stats
18. Flag domains with low acquisition this week

**Data ownership**
19. Plain markdown files in Obsidian vault I control
20. Graph index separate from markdown (fast lookup)
21. Local-first, no hosted account

**MVP boundary**
22. Working web app I can run locally
23. Spec calls out MVP-locked vs product-deferred

---

## 4. Implementation Decisions

### 4.1 Meaning Unit Schema
yaml
---
id: 2026-06-21-001
type: sentence
language: zh
hanzi: "我今天在家吃饭"
pinyin: "wǒ jīntiān zài jiā chī fàn"
english: "I eat at home today"   # HIDDEN — semantic search only
confidence: 0.92
flagged: false
tags: [daily, food, verb]
domains: [daily-life, food]
acquired: 2026-06-21
source: wechat-2026-06-21
words: [吃, 饭, 我, 今天, 家, 在]   # derived, not authored
connections: [2026-06-21-002, ...] # sentences sharing >= 1 word
---
### 4.2 Hidden English Rule
- English is a **semantic class**, never rendered in UI
- Code review checklist enforces: no `english` in render path
- CI gate: invariant test that `english` never appears in search result payload

### 4.3 Dual Search Engine
- **Semantic:** vector similarity over English embeddings (query never sees English)
- **Lexical:** exact/substring match on `hanzi` and `pinyin`
- Results de-duplicated by `id`, re-ranked by combined score
- User doesn't choose — both always run

### 4.4 Review Queue — Flagged Only
- AI proposes; user reviews **only what AI is unsure about**
 (2/5)
- Flag criteria: confidence < 0.7, ambiguous segmentation, novel usage, duplicates, multiple plausible domains
- High-confidence → directly to vault; Low-confidence → pending/

### 4.5 Platform
- **Frontend:** browser web app (Svelte or React, decision deferred to M1)
- **Backend:** Python (FastAPI)
- **Data store:** Obsidian vault — one `.md` per Meaning Unit
- **Graph index:** local JSON/numpy, rebuildable from vault
- **Folder structure:**

language-brain/
  units/       # approved Meaning Units
  pending/     # flagged proposals
  raw/         # pasted chat logs
  index/       # graph index, embeddings cache
  analysis/    # weekly reports
  scripts/     # pipeline scripts
  app/         # web app source
### 4.6 Data Flow

Paste chat log → segment sentences → LLM extract with confidence
→ compute words, connections, embeddings
→ confidence gate: >= 0.7 → vault; < 0.7 → pending/
→ User reviews pending/ only
→ Approved moved to units/ → index rebuilt
→ User searches → merged semantic + lexical results
### 4.7 Tech Stack (MVP)
| Layer | Choice |
|-------|--------|
| Frontend | Svelte (likely) or React |
| Backend | Python FastAPI |
| Data store | Markdown + YAML in Obsidian vault |
| Graph index | Local JSON / numpy |
| Embeddings | Local sentence-transformers (free at small scale) |
| LLM | MiniMax API (M2.7/M3) |
| Word segmentation | jieba-py |
| Pinyin | pypinyin |
| Tests | pytest (backend) + Vitest (frontend) |

**Explicitly NOT:** Langflow, Pinecone/Chroma, Docker, cloud DB, Auth/OAuth.

---

## 5. Testing Decisions

Three test classes:
1. **Behavior tests** — given input X, system produces output Y (through public API)
2. **Schema tests** — Meaning Unit round-trips through vault unchanged
3. **Invariant tests** — properties that must always hold (e.g. no `english` in UI payload)

**Priority order:** Search API → Review queue gate → Vault I/O → Indexer → Pipeline
 (3/5)
**CI gate:** "no English in UI" invariant test must pass to merge.

---

## 6. Out of Scope (Post-MVP)

Multi-user, hosting/cloud, spaced repetition (SRS), Telegram quick-capture, multiple target languages, mobile UI, advanced graph analytics, cross-device sync, public API, collaborative review, translation memory.

---

## 7. Open Questions (pre-M1)

- [ ] Local vs API embeddings cost — lean local for MVP
- [ ] Confidence threshold 0.7 — tune after a week of real use
- [ ] Word-segmentation tool — lean jieba-py
- [ ] Connection definition — word-share only in MVP
- [ ] Pinyin generation — lean pypinyin on extraction
- [ ] Vault location & git strategy — lean sibling dir, `units/` git-ignored
- [ ] React vs Svelte — decision deferred to M1 spike
- [ ] Langflow v0.1 sketch — move to `scratch/langflow-v0.1-sketch.md`

---

## 8. Milestones

- **M0 (3 days):** Vault dir created, schema validated, 10 hand-authored units for round-trip testing, `templates/unit.md`
- **M1 (1 week):** Paste chat log → sentences segmented → LLM extracts Meaning Units → confidence gate → vault/pending. CLI/script-driven, no UI yet
- **M2 (1 week):** Web app shell, search bar, tabular results, semantic + lexical wired up, `english` invariant test
- **M3 (3–4 days):** Review queue UI — pending items, Approve/Edit/Reject, flag reason visible
- **M4 (1 week):** Indexer + graph view — word segmentation, connections, embeddings cache, graph visualization (secondary)
- **M5 (3–4 days):** Coverage dashboard, weekly stats, low-acquisition domain flagging
- **M6 (2 weeks usage):** Solo validate on real material, fix broken things, tune confidence threshold

**M0–M3 = MVP. M4–M6 = post-MVP validation.**

---

## 9. Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | Svelte (likely) | Solo dev velocity, small bundle |
| Backend | Python FastAPI | Same as pipeline, good async |
| Data store | Obsidian vault | User owns data, greppable |
 (4/5)
| Graph index | Local JSON/numpy | No external service at solo scale |
| Embeddings | Local sentence-transformers | Free, fast at small scale |
| LLM | MiniMax API | Already in use |
| Segmentation | jieba-py | Fast, accurate enough |
| Pinyin | pypinyin | Standard, tone-aware |
| Tests | pytest + Vitest | Standard for each ecosystem |

---

## 10. References

- Skill template: `/vault/tools/workflow/to-spec.md`
- Prior version: `SPEC.md` v0.1 (superseded)
- Methodology: `/vault/matt-pocock-study.md`
- Sibling project: `/vault/projects/persona-context/`
- This spec was written from the `light` profile session

---

## Changelog

- **v0.2 (2026-06-21):** Major rewrite — sentence is first-class, English hidden semantic class, dual search engine, flagged-only review queue, web app + Obsidian vault, solo MVP explicit, Langflow deferred, 10-section structure
- **v0.1.1 (2026-06-21):** Added `concept_id`, git/versioning strategy, Langflow + Python split
- **v0.1 (2026-06-21):** Initial spec — word-first, sentences as body, Langflow pipeline planned
 (5/5)
