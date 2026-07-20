// Typed fetch wrapper for the FastAPI backend.
// Mirrors the contracts defined in SPEC §5.3.

export type UnitType = 'sentence' | 'word' | 'group' | 'compound';
export type VaultBrowseType = 'sentence' | 'word' | 'compound';
export type VaultSortKey = 'id' | 'pinyin';
export type ConnectionKind = 'lexical' | 'semantic' | 'group' | 'opposite';

export interface SearchResult {
  id: string;
  type: UnitType;
  name: string;
  snippet: string;
  kinds: ConnectionKind[];
  score: number;
  containing_sentences?: string[];
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
}

// Vault browse (v0.7) — mirrors GET /api/vault/list response shape.
export interface VaultListItem {
  id: string;
  name: string;
  snippet: string;
}

export interface VaultListResponse {
  type: VaultBrowseType;
  total: number;
  limit: number;
  offset: number;
  sort: VaultSortKey;
  items: VaultListItem[];
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

// Commit-sentence request. Mirrors api/schemas.py's CommitSentenceRequest.
// The backend assigns the sentence id via a monotonic counter (S1, S2, ...).
export interface CommitSentenceRequest {
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

// Unit detail (T32/T33, AC26/AC27). The endpoint returns the full
// unit dict as it lives on disk — author view, includes english/
// meaning. Frontend is responsible for not leaking these in search-
// result contexts. Word units additionally carry `containing_sentences`
// (a list of sentence ids whose words[]/word_refs[] include this
// word). Per AC27 the word never renders alone — it is always shown
// in the context of its containing sentences.
export interface UnitDetail {
  id: string;
  type: UnitType;
  name: string;
  properties: Record<string, unknown>;
  connections: { to: string; kind: ConnectionKind; score: number; name?: string }[];
  created: string;
  updated: string;
  author_confirmed: boolean;
  containing_sentences?: { id: string; name: string }[];
  constituent_characters?: { id: string; name: string }[];
  word_refs_resolved?: Record<string, string>;
  groups_resolved?: Record<string, string>;
}

export async function getUnit(id: string): Promise<UnitDetail> {
  const res = await fetch(`${API_BASE}/api/units/${encodeURIComponent(id)}`);
  if (res.status === 404) {
    throw new Error(`unit ${id} not found`);
  }
  if (!res.ok) throw new Error(`getUnit failed: ${res.status}`);
  return res.json();
}

// Base URL — overridable via VITE_API_BASE env var.
// Defaults to same-origin relative path (works in production when the
// API is served from the same host as the static frontend).
export const API_BASE = (import.meta as any).env?.VITE_API_BASE ?? '';

export async function search(q: string, opts: { kinds?: ConnectionKind[]; types?: UnitType[]; signal?: AbortSignal } = {}): Promise<SearchResponse> {
  const params = new URLSearchParams({ q });
  if (opts.kinds) params.set('kinds', opts.kinds.join(','));
  if (opts.types) params.set('types', opts.types.join(','));
  const res = await fetch(`${API_BASE}/api/search?${params}`, { signal: opts.signal });
  if (!res.ok) throw new Error(`search failed: ${res.status}`);
  return res.json();
}

export async function suggest(
  q: string,
  limit = 5,
  signal?: AbortSignal,
  types?: string[]
): Promise<SuggestResult[]> {
  const params = new URLSearchParams({ q, limit: String(limit) });
  if (types?.length) params.set('types', types.join(','));
  const res = await fetch(`${API_BASE}/api/search/suggest?${params}`, { signal });
  if (!res.ok) throw new Error(`suggest failed: ${res.status}`);
  return res.json();
}

export async function vaultList(
  type: VaultBrowseType,
  opts: { limit?: number; offset?: number; sort?: VaultSortKey } = {}
): Promise<VaultListResponse> {
  const params = new URLSearchParams({ type });
  if (opts.limit != null) params.set('limit', String(opts.limit));
  if (opts.offset != null) params.set('offset', String(opts.offset));
  if (opts.sort) params.set('sort', opts.sort);
  const res = await fetch(`${API_BASE}/api/vault/list?${params}`);
  if (!res.ok) throw new Error(`vaultList failed: ${res.status}`);
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

export interface EditSentenceRequest {
  hanzi: string;
  pinyin: string;
  english: string;
  meaning: string;
  words: string[];
  word_refs: string[];
  groups: (ProposedGroup | string)[];
  antonyms: string[];
}

export interface EditSentenceResponse {
  id: string;
  updated: string;
  connections_summary: Record<string, number>;
  groups_added: string[];
  groups_removed: string[];
}

export async function editSentence(
  id: string,
  body: EditSentenceRequest
): Promise<EditSentenceResponse> {
  const res = await fetch(`${API_BASE}/api/sentences/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`editSentence failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export interface EditWordRequest {
  english: string;
  meaning: string;
  groups: (ProposedGroup | string)[];
  antonyms: string[];
}

export interface EditWordResponse {
  id: string;
  type: string;
  updated: string;
  connections_summary: Record<string, number>;
  groups_added: string[];
  groups_removed: string[];
  antonyms_added: string[];
  antonyms_removed: string[];
}

export async function editWord(
  id: string,
  body: EditWordRequest
): Promise<EditWordResponse> {
  const res = await fetch(`${API_BASE}/api/words/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`editWord failed: ${res.status}: ${detail}`);
  }
  return res.json();
}

// ─── Version info ─────────────────────────────────────────────────────────────

export interface VersionInfo {
  version: string;
  git_commit: string;
  git_branch: string;
  python_version?: string;
  timestamp?: string;
}

export async function getVersion(): Promise<VersionInfo> {
  const res = await fetch(`${API_BASE}/api/version`);
  if (!res.ok) throw new Error(`getVersion failed: ${res.status}`);
  return res.json();
}
