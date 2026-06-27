// Typed fetch wrapper for the FastAPI backend.
// Mirrors the contracts defined in SPEC §5.3.

export type UnitType = 'sentence' | 'word' | 'group';
export type ConnectionKind = 'lexical' | 'semantic' | 'group' | 'opposite';

export interface SearchResult {
  id: string;
  type: UnitType;
  name: string;
  snippet: string;
  kinds: ConnectionKind[];
  score: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
}

export interface SuggestResult {
  id: string;
  type: UnitType;
  name: string;
}

// Types for the add-sentence flow (T31, AC25).

export interface ProposedGroup {
  id: string;
  display_name: string;
  description: string;
}

export interface ProposedLabels {
  pinyin: string;
  english: string;
  meaning: string;
  words: string[];
  word_refs: string[];
  groups: ProposedGroup[];
  antonyms: string[];
}

// Commit-sentence request (T31, AC25). Mirrors api/schemas.py's
// CommitSentenceRequest. The id is the stable sentence slug the
// frontend derives from pinyin (e.g. "wo-xihuan-chi") so re-saves
// don't churn filenames.
export interface CommitSentenceRequest {
  id: string;
  hanzi: string;
  pinyin: string;
  english: string;
  meaning: string;
  words: string[];
  word_refs: string[];
  groups: (ProposedGroup | string)[];
  antonyms: string[];
  author_confirmed: boolean;
}

export interface CommitSentenceResponse {
  id: string;
  saved_at: string;
  word_ids_created: string[];
  group_ids_created: string[];
}

// Base URL — overridable in dev. Default points at the FastAPI backend.
export const API_BASE = (typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_API_BASE)
  || 'http://localhost:8000';

export async function search(q: string, opts: { kinds?: ConnectionKind[]; types?: UnitType[]; signal?: AbortSignal } = {}): Promise<SearchResponse> {
  const params = new URLSearchParams({ q });
  if (opts.kinds) params.set('kinds', opts.kinds.join(','));
  if (opts.types) params.set('types', opts.types.join(','));
  const res = await fetch(`${API_BASE}/api/search?${params}`, { signal: opts.signal });
  if (!res.ok) throw new Error(`search failed: ${res.status}`);
  return res.json();
}

export async function suggest(q: string, limit = 5, signal?: AbortSignal): Promise<SuggestResult[]> {
  const params = new URLSearchParams({ q, limit: String(limit) });
  const res = await fetch(`${API_BASE}/api/search/suggest?${params}`, { signal });
  if (!res.ok) throw new Error(`suggest failed: ${res.status}`);
  return res.json();
}

export async function proposeLabels(hanzi: string, note: string): Promise<ProposedLabels> {
  const res = await fetch(`${API_BASE}/api/sentences`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ hanzi, note })
  });
  if (!res.ok) throw new Error(`propose failed: ${res.status}`);
  return res.json();
}

export async function commitSentence(body: CommitSentenceRequest): Promise<CommitSentenceResponse> {
  const res = await fetch(`${API_BASE}/api/sentences/commit`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`commit failed: ${res.status} ${detail}`);
  }
  return res.json();
}
