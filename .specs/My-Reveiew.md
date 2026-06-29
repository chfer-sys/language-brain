The search bar when i type in english like (i want to eat) also should show sentences that related to "eat" 
Those sentences already have english hidden in it for example 吃 means eating

And i want nontechnical explanation 
Because this language graph is node based thats called unit


---————
This is for the next phase 
dont do anything about this now

use the same system but add for grammar as unit on separate database. User can search grammar based on input so its more like grammsr library
——————

---

## v0.4.1 follow-up (shipped 2026-06-29)

The "search bar typing english should show sentences related to
eat" feedback was addressed in v0.4.1 (commits `4dcc86e`,
`730cd98`, `0f3f822` on `kickoff/v0.4.1-english-search`).

Three changes:

1. **Threshold tunable.** `LANGUAGE_BRAIN_SEMANTIC_THRESHOLD`
   env var and `?threshold=` query param on `/api/search`. Default
   stays at 0.6 per SPEC.

2. **English propagation.** New commits auto-fill
   `word.properties.english` from the sentence's english field
   when committing. A one-shot backfill script populated 14
   existing word units.

3. **Lexical pass now matches English queries.** The query
   token set unions char-level and whole-word tokens; the unit
   scorer takes max Jaccard across hanzi/english/meaning; group
   slug substring match preserved, display_name switched to
   whole-word.

Live verified: `GET /api/search?q=i+want+to+eat` returns
吃 word unit at score 0.4, then 我想吃 sentence, then 我/想
word units. No more emotion/drinks false positives.
