/**
 * normalizeSources - Detect search/RAG-shaped tool outputs and extract a
 * uniform list of sources for aggregated rendering.
 *
 * Pure data normalisation: takes a tool name + raw output (already a string,
 * usually JSON-serialised by the backend) and returns a list of `Source`
 * records when the shape matches a known search/retrieval pattern.
 *
 * No semantic judgement — only structural detection. Returns `null` when the
 * shape does not match.
 */

export interface Source {
  readonly title: string;
  readonly url?: string | undefined;
  readonly snippet?: string | undefined;
  readonly score?: number | undefined;
  readonly sourceType: 'web' | 'rag' | 'graph' | 'other';
  readonly toolName: string;
}

const SEARCH_TOOL_PATTERNS: ReadonlyArray<RegExp> = [
  /(^|_)search($|_)/i,
  /web_scrape/i,
  /retriev/i,
  /^rag(_|$)/i,
  /memory_(search|recall)/i,
  /knowledge_(search|graph)/i,
  /(^|_)kg(_|$)/i,
  /(^|_)hits($|_)/i,
];

const SOURCE_TYPE_MAP: ReadonlyArray<readonly [RegExp, Source['sourceType']]> = [
  [/web|search|scrape|browse/i, 'web'],
  [/rag|retriev|memory|recall|vector|embedding/i, 'rag'],
  [/graph|kg|neo4j|entity|relation/i, 'graph'],
];

function classifyToolName(toolName: string): Source['sourceType'] {
  for (const [pattern, type] of SOURCE_TYPE_MAP) {
    if (pattern.test(toolName)) return type;
  }
  return 'other';
}

function isSearchShapedTool(toolName: string): boolean {
  return SEARCH_TOOL_PATTERNS.some((re) => re.test(toolName));
}

function tryParseJson(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function readString(obj: Record<string, unknown>, keys: ReadonlyArray<string>): string | undefined {
  for (const key of keys) {
    const v = obj[key];
    if (typeof v === 'string' && v.trim().length > 0) return v;
  }
  return undefined;
}

function readNumber(obj: Record<string, unknown>, keys: ReadonlyArray<string>): number | undefined {
  for (const key of keys) {
    const v = obj[key];
    if (typeof v === 'number' && Number.isFinite(v)) return v;
  }
  return undefined;
}

function extractCandidate(
  raw: unknown,
  toolName: string,
  sourceType: Source['sourceType']
): Source | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as Record<string, unknown>;
  const url = readString(obj, ['url', 'link', 'href', 'source', 'uri']);
  const title = readString(obj, ['title', 'name', 'heading', 'document_title', 'entity_name']);
  const snippet = readString(obj, [
    'snippet',
    'summary',
    'text',
    'content',
    'description',
    'excerpt',
    'chunk',
  ]);
  // A candidate must have at least a title or a snippet+url to be useful.
  if (!title && !(snippet && url)) return null;
  const score = readNumber(obj, ['score', 'relevance', 'similarity', 'rank_score']);
  const result: Source = {
    title: title || url || (snippet ? snippet.slice(0, 80) : 'Untitled'),
    sourceType,
    toolName,
    ...(url !== undefined ? { url } : {}),
    ...(snippet !== undefined ? { snippet } : {}),
    ...(score !== undefined ? { score } : {}),
  };
  return result;
}

const HIT_LIST_KEYS: ReadonlyArray<string> = [
  'results',
  'hits',
  'items',
  'matches',
  'documents',
  'sources',
  'citations',
  'data',
];

function extractCandidates(parsed: unknown): ReadonlyArray<Record<string, unknown>> {
  if (Array.isArray(parsed)) {
    return parsed.filter((x): x is Record<string, unknown> => !!x && typeof x === 'object');
  }
  if (parsed && typeof parsed === 'object') {
    const obj = parsed as Record<string, unknown>;
    for (const key of HIT_LIST_KEYS) {
      const v = obj[key];
      if (Array.isArray(v)) {
        return v.filter((x): x is Record<string, unknown> => !!x && typeof x === 'object');
      }
    }
  }
  return [];
}

/**
 * Try to extract a list of sources from a single tool execution.
 * Returns `null` when the tool name or output shape does not look like a
 * search/retrieval result — the caller should fall back to its default
 * rendering in that case.
 */
export function normalizeToolSources(
  toolName: string,
  output: string | Record<string, unknown> | undefined | null
): ReadonlyArray<Source> | null {
  if (!output) return null;
  if (!isSearchShapedTool(toolName)) return null;

  const parsed = typeof output === 'string' ? tryParseJson(output) : output;
  if (parsed === null || parsed === undefined) return null;

  const sourceType = classifyToolName(toolName);
  const candidates = extractCandidates(parsed);
  if (candidates.length === 0) return null;

  const sources: Source[] = [];
  for (const cand of candidates) {
    const src = extractCandidate(cand, toolName, sourceType);
    if (src) sources.push(src);
  }
  if (sources.length === 0) return null;
  return sources;
}

/**
 * Aggregate sources across multiple tool calls within one turn, deduping by
 * URL (case-insensitive) and falling back to title+toolName when no URL.
 * Preserves original order; later duplicates are dropped.
 */
export function aggregateSources(
  perStep: ReadonlyArray<ReadonlyArray<Source>>
): ReadonlyArray<Source> {
  const seen = new Set<string>();
  const result: Source[] = [];
  for (const list of perStep) {
    for (const src of list) {
      const key = src.url
        ? `url:${src.url.toLowerCase()}`
        : `t:${src.toolName}:${src.title.toLowerCase()}`;
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(src);
    }
  }
  return result;
}

/**
 * Group a flat source list by domain (for `web` type) or by toolName (for
 * everything else). Returns insertion-ordered groups.
 */
export interface SourceGroup {
  readonly key: string;
  readonly label: string;
  readonly sources: ReadonlyArray<Source>;
}

function domainOf(url: string): string {
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./i, '');
  } catch {
    return 'unknown';
  }
}

export function groupSources(sources: ReadonlyArray<Source>): ReadonlyArray<SourceGroup> {
  const groups = new Map<string, Source[]>();
  const labels = new Map<string, string>();
  for (const src of sources) {
    let key: string;
    let label: string;
    if (src.sourceType === 'web' && src.url) {
      const dom = domainOf(src.url);
      key = `web:${dom}`;
      label = dom;
    } else {
      key = `tool:${src.toolName}`;
      label = src.toolName;
    }
    const list = groups.get(key);
    if (list) {
      list.push(src);
    } else {
      groups.set(key, [src]);
      labels.set(key, label);
    }
  }
  return Array.from(groups.entries()).map(([key, sourceList]) => ({
    key,
    label: labels.get(key) ?? key,
    sources: sourceList,
  }));
}
