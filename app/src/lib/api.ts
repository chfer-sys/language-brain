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
