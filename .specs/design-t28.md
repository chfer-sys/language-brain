# T28 Design Doc — Default Page (AC22)

**Task:** T28 — AC22 — Default page (`/`) renders a search box, no other content above the fold.
**Branch:** `kickoff/T28-ac22-default-page` (branched off `kickoff/T27-meanings-route` at `5dff0f6`).
**Author:** orchestrator → waiting on your input before coding.
**Goal of this doc:** lock the look-and-feel decisions so T28 builds the right thing on the first commit and we have a web preview to collaborate on.

---

## 1. What's locked (do not re-litigate)

- **Tech:** SvelteKit + TypeScript + Vitest. Backend already MVP-complete (430 tests pass).
- **AC22 contract:** `/` shows a search box above the fold and **nothing else** above the fold. Toggles/filters/results live **below the fold** (those come in T29/T30). The Add-sentence link lives below the fold too.
- **English is hidden in result UI.** On the default page, that means: search input itself shows whatever the user types (it's their input — English allowed), but no English text appears as labels or chrome.
- **Stack: bare SvelteKit.** No Tailwind, no component library, no design system. Plain CSS in `+page.svelte` (or co-located `<style>`). One dev dependency: SvelteKit + Vite + TS + vitest + @testing-library/svelte.

---

## 2. The four decisions that change the look

These are the questions I need you to answer. I've put my recommendation first in each, marked **(Recommended)**.

### 2.1 Search box layout — centered hero vs. top-anchored bar

| Option | What it looks like |
|---|---|
| **A. Centered hero (Recommended)** | Big search input, vertically + horizontally centered in the viewport. Logo/title above. Results drop down below the fold when the user types. Reads as "search engine" (Google, DuckDuckGo). |
| B. Top-anchored bar | Search input fixed near the top of the viewport, like Notion / Linear / GitHub. More app-like, less landing-page-like. |
| C. Minimal full-bleed | Just a thin input centered, no title, no chrome. Maximalist-minimal. |

My take: **A** matches the "search-first, one search box is the home page" framing in SPEC §3.2 and the "looks like Google" mental model a learner has when they want to find a sentence they remember.

### 2.2 Title / branding

What shows **above** the search box?

| Option | What it shows |
|---|---|
| **A. "Language Brain" wordmark only (Recommended)** | Plain text, no logo, no tagline. The name carries the brand. |
| B. "Language Brain" + small Chinese tagline (e.g. 语言大脑) | Bilingual mark. |
| C. No title at all | Search box only. Pure utility. |
| D. Logo glyph + wordmark | I'd need you to point me at an SVG / image, or describe one. |

### 2.3 Placeholder text inside the search box

This is the **prompt** the user sees before they type. It teaches them what the box does.

| Option | Placeholder |
|---|---|
| **A. (Recommended)** | `Search a sentence, word, or group…` (or in mixed CJK: `搜句子、词或词组…`) |
| B. Just Chinese | `搜句子、词或词组…` |
| C. Just English | `Search a sentence, word, or group…` |
| D. Two examples | `Try: 看起来好吃 or 吃 or basic-verbs` — teaches by example |

### 2.4 "+ Add sentence" affordance

SPEC §3.1 step 2 says the user clicks **+ Add sentence** to enter authoring mode. Where does this live on the default page?

| Option | Where it lives |
|---|---|
| **A. Top-right corner link, below the fold (Recommended)** | Plain text link, top-right of viewport. Doesn't compete with the search box for attention. AC22 says "no other content above the fold" so this sits *just below* the search box. |
| B. Below the search box, centered, as a text link | Reads like "Can't find what you're looking for? + Add sentence" |
| C. Floating action button (bottom-right) | App-like. |

---

## 3. Decisions I am making for you (no need to answer)

These are small enough that I'll just pick a sensible default. Push back if you hate them:

- **No dark mode toggle in T28.** Pure white background, dark text. We can add a theme later.
- **System font stack** (no Google Fonts, no @font-face). Fast, offline-friendly.
- **Search box width:** `min(640px, 90vw)`. Big enough to feel intentional, capped so it doesn't span ultrawide monitors.
- **Focus ring:** native browser ring (no custom outline). Accessibility-first.
- **No results state shown in T28.** Empty input → no results pane. T29 wires that up.
- **No "press / to focus" keyboard hint.** Add it later if you want.

---

## 4. What I will deliver in T28 (once you answer §2)

1. `app/src/routes/+page.svelte` — the default page. Search input centered, title above it, "+ Add sentence" link in the corner.
2. `app/src/lib/api.ts` — typed fetch wrapper for the FastAPI backend on `http://localhost:8000`. Defines the `SearchResult` / `SuggestResult` shapes from SPEC §5.3.
3. `app/src/lib/components/SearchBox.svelte` — the input. Emits `query` on input. Will accept a debounce prop in T29.
4. `app/src/lib/components/ResultRow.svelte` — placeholder (renders name + snippet). Full wiring in T29/T30. **Stub now so the file exists.**
5. `app/src/lib/components/KindToggles.svelte` — placeholder. Stub.
6. `app/src/lib/components/UnitTypeFilters.svelte` — placeholder. Stub.
7. `app/src/lib/components/AddSentenceForm.svelte` — placeholder. Stub.
8. `app/src/app.css` — global styles (font stack, body reset, color tokens).
9. `app/svelte.config.js` — real config (SvelteKit + vite plugin).
10. `app/vite.config.ts` — real config (SvelteKit plugin + vitest).
11. `app/src/app.html` — SvelteKit HTML shell.
12. `app/tests/` — Vitest test for the default page: confirms the input is rendered and is the only thing above the fold (height test against a 800px viewport).
13. `app/package.json` — installed deps (SvelteKit + Vite + TS + vitest + testing-library).
14. `app/tsconfig.json` — TS config.

**Tests:** one Vitest test, mirrors the spirit of AC22. Manual check by you in Chrome.
**Commit:** single commit on the T28 branch. `npm run dev` will start a local preview you can open in Chrome.

---

## 5. The "web preview" workflow

Once T28 is built:

```bash
cd app && npm install          # one-time, ~1-3 min
cd .. && docker run --rm -p 8000:8000 \
    -v $(pwd):/work -w /work \
    -e LANGUAGE_BRAIN_VAULT=$(pwd)/vault \
    kilo-language-brain-test \
    uvicorn api.app:app --host 0.0.0.0 --port 8000
# in another shell:
cd app && npm run dev          # opens http://localhost:5173
```

You open Chrome → `http://localhost:5173` → see the search box. Type hanzi/pinyin/English → results drop in below the fold (T29).

---

## 6. Open questions for you (please answer)

1. **§2.1 layout** — A (centered hero) / B (top bar) / C (minimal)?
2. **§2.2 title** — A (wordmark) / B (bilingual) / C (none) / D (logo)?
3. **§2.3 placeholder** — A (English "Search a sentence, word, or group…") / B (Chinese) / C (both) / D (examples)?
4. **§2.4 add-sentence link** — A (top-right, below fold) / B (centered below box) / C (FAB)?

If you say "your call" or "go with recommendations" I'll just build A+A+A+A.

---

## 7. After T28 lands

The web preview will be live. We can iterate visually:
- T29: debounce + result pane below the fold
- T30: kind-toggles + unit-type filters (clickable, no reload)
- T31: add-sentence page
- T32/T33: unit detail pages

End-of-MVP after that = T34 (qa-reviewer + docs-writer + trace).