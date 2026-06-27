<script lang="ts">
  import {
    proposeLabels,
    commitSentence,
    type ProposedLabels,
    type ProposedGroup
  } from '$lib/api';

  let hanzi = '';
  let note = '';
  let proposed: ProposedLabels | null = null;
  let proposing = false;
  let committing = false;
  let error: string | null = null;
  let savedId: string | null = null;

  // Editable copies of the AI's proposed fields. The user can adjust
  // any of these before saving. We keep them as plain strings (or
  // arrays) rather than binding to the ProposedLabels object so the
  // raw AI response stays immutable for diff/reset.
  let pinyin = '';
  let english = '';
  let meaning = '';
  let wordsCsv = '';
  let wordRefsCsv = '';
  let groupsCsv = '';
  let antonymsCsv = '';

  function arrayToCsv(items: string[]): string {
    return items.join(', ');
  }

  function csvToArray(csv: string): string[] {
    return csv
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
  }

  function groupsToCsv(groups: ProposedGroup[]): string {
    return groups.map((g) => g.display_name || g.id).join(', ');
  }

  function groupsFromCsv(csv: string): ProposedGroup[] {
    return csvToArray(csv).map((name) => {
      const slug = name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');
      return { id: slug, display_name: name, description: '' };
    });
  }

  function resetProposalState() {
    proposed = null;
    pinyin = '';
    english = '';
    meaning = '';
    wordsCsv = '';
    wordRefsCsv = '';
    groupsCsv = '';
    antonymsCsv = '';
    // Note: deliberately does NOT reset `error` — callers that use this
    // helper on success want to clear error too; callers on failure
    // already set their own error.
  }

  async function onPropose() {
    error = null;
    if (hanzi.trim().length === 0) {
      error = 'Type a hanzi sentence first.';
      return;
    }
    proposing = true;
    try {
      const resp = await proposeLabels(hanzi.trim(), note.trim());
      proposed = resp;
      pinyin = resp.pinyin;
      english = resp.english;
      meaning = resp.meaning;
      wordsCsv = arrayToCsv(resp.words);
      wordRefsCsv = arrayToCsv(resp.word_refs);
      groupsCsv = groupsToCsv(resp.groups);
      antonymsCsv = arrayToCsv(resp.antonyms);
      // On success, clear any prior error.
      error = null;
    } catch (e) {
      // On failure, keep error visible; clear any prior proposal.
      error = e instanceof Error ? e.message : String(e);
      proposed = null;
      pinyin = '';
      english = '';
      meaning = '';
      wordsCsv = '';
      wordRefsCsv = '';
      groupsCsv = '';
      antonymsCsv = '';
    } finally {
      proposing = false;
    }
  }

  async function onSave() {
    error = null;
    if (hanzi.trim().length === 0 || pinyin.trim().length === 0) {
      error = 'Both hanzi and pinyin are required.';
      return;
    }
    committing = true;
    try {
      // Derive a stable id from the pinyin so re-saves don't churn
      // filenames. ASCII letters/digits only; non-ASCII falls back
      // to a date-based id.
      const slug = pinyin
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '');
      const id = slug.length > 0 ? slug : new Date().toISOString().slice(0, 10).replace(/-/g, '');

      const resp = await commitSentence({
        id,
        hanzi: hanzi.trim(),
        pinyin: pinyin.trim(),
        english: english.trim(),
        meaning: meaning.trim(),
        words: csvToArray(wordsCsv),
        word_refs: csvToArray(wordRefsCsv),
        groups: groupsFromCsv(groupsCsv),
        antonyms: csvToArray(antonymsCsv),
        author_confirmed: true
      });
      savedId = resp.id;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      committing = false;
    }
  }

  function onStartOver() {
    hanzi = '';
    note = '';
    savedId = null;
    resetProposalState();
  }
</script>

<svelte:head>
  <title>Add sentence · Language Brain</title>
</svelte:head>

<main class="page">
  <header class="header">
    <a class="back" href="/">← Back</a>
    <h1>Add a sentence</h1>
    <p class="hint">Type hanzi, optionally add an English hint, then click "Propose labels" to get the AI's draft. Edit any field before saving.</p>
  </header>

  {#if savedId}
    <section class="saved" data-testid="saved">
      <h2>Saved</h2>
      <p>Sentence unit <code>{savedId}</code> written to the vault.</p>
      <div class="actions">
        <button type="button" on:click={onStartOver}>Add another</button>
        <a href="/">Go to search</a>
      </div>
    </section>
  {:else}
    <form class="form" on:submit|preventDefault={onPropose}>
      <label class="field">
        <span class="label">Hanzi</span>
        <textarea
          bind:value={hanzi}
          placeholder="我流口水了"
          rows="2"
          data-testid="hanzi-input"
        ></textarea>
      </label>

      <label class="field">
        <span class="label">English hint (optional)</span>
        <input
          type="text"
          bind:value={note}
          placeholder="A short note to disambiguate the sentence"
        />
      </label>

      <div class="actions">
        <button
          type="submit"
          class="primary"
          disabled={proposing || hanzi.trim().length === 0}
          data-testid="propose-btn"
        >
          {proposing ? 'Proposing…' : 'Propose labels'}
        </button>
      </div>
    </form>

    {#if error}
      <p class="error" role="alert">{error}</p>
    {/if}

    {#if proposed}
      <section class="proposed" data-testid="proposed-form">
        <h2>Review &amp; edit</h2>
        <p class="hint">Each field is editable. The AI's draft is loaded below.</p>

        <label class="field">
          <span class="label">Pinyin</span>
          <input type="text" bind:value={pinyin} data-testid="pinyin-input" />
        </label>

        <label class="field">
          <span class="label">English</span>
          <input type="text" bind:value={english} />
        </label>

        <label class="field">
          <span class="label">Meaning (richer gloss for semantic search)</span>
          <input type="text" bind:value={meaning} />
        </label>

        <label class="field">
          <span class="label">Words (comma-separated hanzi tokens)</span>
          <input type="text" bind:value={wordsCsv} />
        </label>

        <label class="field">
          <span class="label">Word refs (comma-separated pinyin-with-tones)</span>
          <input type="text" bind:value={wordRefsCsv} />
        </label>

        <label class="field">
          <span class="label">Groups (comma-separated)</span>
          <input type="text" bind:value={groupsCsv} />
        </label>

        <label class="field">
          <span class="label">Antonyms (comma-separated pinyin-with-tones)</span>
          <input type="text" bind:value={antonymsCsv} />
        </label>

        <div class="actions">
          <button
            type="button"
            class="primary"
            on:click={onSave}
            disabled={committing || hanzi.trim().length === 0 || pinyin.trim().length === 0}
            data-testid="save-btn"
          >
            {committing ? 'Saving…' : 'Save'}
          </button>
          <button type="button" on:click={onStartOver}>Cancel</button>
        </div>
      </section>
    {/if}
  {/if}
</main>

<style>
  .page {
    max-width: 640px;
    margin: 0 auto;
    padding: 32px 24px 64px;
  }

  .header {
    margin-bottom: 32px;
  }

  .back {
    font-size: 13px;
    color: var(--lb-accent);
    text-decoration: none;
    display: inline-block;
    margin-bottom: 12px;
  }

  .back:hover,
  .back:focus-visible {
    text-decoration: underline;
  }

  .header h1 {
    font-size: 28px;
    font-weight: 600;
    margin: 0 0 8px;
    color: var(--lb-fg);
  }

  .hint {
    color: var(--lb-muted);
    font-size: 14px;
    margin: 0;
  }

  .form,
  .proposed,
  .saved {
    display: flex;
    flex-direction: column;
    gap: 18px;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .field .label {
    font-size: 13px;
    font-weight: 500;
    color: var(--lb-fg);
  }

  .field input,
  .field textarea {
    font: inherit;
    font-size: 15px;
    padding: 10px 12px;
    border: 1px solid var(--lb-border);
    border-radius: 8px;
    background: var(--lb-bg);
    color: var(--lb-fg);
    outline: none;
    transition: border-color 100ms ease, box-shadow 100ms ease;
  }

  .field input:focus,
  .field textarea:focus {
    border-color: var(--lb-accent);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
  }

  .actions {
    display: flex;
    gap: 12px;
    align-items: center;
  }

  button,
  .actions a {
    font: inherit;
    font-size: 14px;
    padding: 9px 16px;
    border-radius: 8px;
    border: 1px solid var(--lb-border);
    background: var(--lb-bg);
    color: var(--lb-fg);
    cursor: pointer;
    text-decoration: none;
  }

  button.primary {
    background: var(--lb-accent);
    color: white;
    border-color: var(--lb-accent);
  }

  button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .error {
    color: #b91c1c;
    font-size: 14px;
    margin: 0;
  }

  .proposed h2 {
    font-size: 18px;
    font-weight: 600;
    margin: 24px 0 4px;
  }

  code {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    background: #f1f5f9;
    padding: 1px 6px;
    border-radius: 4px;
    font-size: 13px;
  }
</style>