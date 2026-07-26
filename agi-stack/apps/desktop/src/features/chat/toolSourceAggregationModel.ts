import type { AgentTimelineItem } from '../../types';
import {
  pairToolCallItems,
  toolCallPresentationKind,
  type ToolCallPair,
} from './chatTimelineModel';

export type AggregatedToolSource = {
  id: string;
  title: string;
  url?: string;
  snippet?: string;
  score?: number;
  sourceType: string | null;
  providerLabel: string | null;
};

export type AggregatedToolSourceGroup = {
  key: string;
  label: string | null;
  sources: AggregatedToolSource[];
};

export type ToolSourceAggregation = {
  callCount: number;
  sourceCount: number;
  groups: AggregatedToolSourceGroup[];
};

const EXPLICIT_SOURCE_LIST_KEYS = ['sources', 'citations', 'references'] as const;
const SEARCH_RESULT_LIST_KEYS = ['results', 'hits', 'documents', 'matches'] as const;
const OUTPUT_WRAPPER_KEYS = ['data', 'output', 'result'] as const;
const SOURCE_TYPE_KEYS = ['source_type', 'sourceType'] as const;
const PROVIDER_LABEL_KEYS = ['provider_label', 'providerLabel'] as const;
const TITLE_KEYS = ['title', 'name', 'document_title', 'documentTitle'] as const;
const URL_KEYS = ['url', 'link', 'href', 'uri'] as const;
const SNIPPET_KEYS = ['snippet', 'summary', 'excerpt', 'description', 'content', 'text'] as const;
const SCORE_KEYS = ['score', 'relevance', 'similarity', 'rank_score', 'rankScore'] as const;

export function aggregateStructuredToolSources(
  items: readonly AgentTimelineItem[],
  minimumSourceCalls = 2,
): ToolSourceAggregation | null {
  const toolItems = items.filter((item) => item.type === 'act' || item.type === 'observe');
  const perCallSources = pairToolCallItems(toolItems).flatMap((pair) => {
    const sources = structuredSourcesForPair(pair);
    return sources.length > 0 ? [sources] : [];
  });
  if (perCallSources.length < minimumSourceCalls) return null;

  const sources = deduplicateSources(perCallSources);
  if (sources.length === 0) return null;
  return {
    callCount: perCallSources.length,
    sourceCount: sources.length,
    groups: groupSources(sources),
  };
}

function structuredSourcesForPair(pair: ToolCallPair): AggregatedToolSource[] {
  const parsed = parseStructuredOutput(
    pair.result?.toolOutput ??
      pair.result?.payload ??
      pair.call.toolOutput ??
      pair.call.payload ??
      null,
  );
  const displayPayloads = displayMetadataPayloads(pair);
  const displayMetadata = firstSourceMetadata(displayPayloads);
  const rootMetadata = parsed === null ? emptySourceMetadata() : sourceMetadata(parsed);
  const context = {
    sourceType: rootMetadata.sourceType ?? displayMetadata.sourceType,
    providerLabel: rootMetadata.providerLabel ?? displayMetadata.providerLabel,
  };
  const allowsSearchResultLists =
    toolCallPresentationKind(pair) === 'search' ||
    context.sourceType !== null ||
    context.providerLabel !== null;
  const candidates = [parsed, ...displayPayloads].flatMap((payload) =>
    payload === null ? [] : sourceCandidates(payload, allowsSearchResultLists),
  );

  return candidates.flatMap((candidate, index) => {
    const source = normalizeSourceCandidate(candidate, context, pair.call.id, index);
    return source ? [source] : [];
  });
}

function displayMetadataPayloads(pair: ToolCallPair): Record<string, unknown>[] {
  const payloads: Record<string, unknown>[] = [];
  for (const item of [pair.result, pair.call]) {
    if (!item) continue;
    const directDisplay = isRecord(item.display) ? item.display : null;
    const outputDisplay =
      isRecord(item.toolOutput) && isRecord(item.toolOutput.display)
        ? item.toolOutput.display
        : null;
    for (const display of [directDisplay, outputDisplay]) {
      if (!display) continue;
      const metadata = isRecord(display.metadata) ? display.metadata : display;
      payloads.push(metadata);
    }
  }
  return payloads;
}

function firstSourceMetadata(values: readonly unknown[]): SourceMetadata {
  for (const value of values) {
    const metadata = sourceMetadata(value);
    if (metadata.sourceType !== null || metadata.providerLabel !== null) return metadata;
  }
  return emptySourceMetadata();
}

type SourceMetadata = {
  sourceType: string | null;
  providerLabel: string | null;
};

function sourceMetadata(value: unknown): SourceMetadata {
  if (!isRecord(value)) return emptySourceMetadata();
  return {
    sourceType: readString(value, SOURCE_TYPE_KEYS),
    providerLabel: readString(value, PROVIDER_LABEL_KEYS),
  };
}

function emptySourceMetadata(): SourceMetadata {
  return { sourceType: null, providerLabel: null };
}

function sourceCandidates(
  value: unknown,
  allowsSearchResultLists: boolean,
): Record<string, unknown>[] {
  const roots = structuredRoots(value);
  const candidates: Record<string, unknown>[] = [];
  for (const root of roots) {
    if (Array.isArray(root)) {
      if (allowsSearchResultLists) candidates.push(...recordItems(root));
      continue;
    }
    if (!isRecord(root)) continue;
    for (const key of EXPLICIT_SOURCE_LIST_KEYS) {
      if (Array.isArray(root[key])) candidates.push(...recordItems(root[key]));
    }
    for (const key of SEARCH_RESULT_LIST_KEYS) {
      if (Array.isArray(root[key]) && allowsSearchResultLists) {
        candidates.push(...recordItems(root[key]));
      }
    }
  }
  return candidates;
}

function structuredRoots(value: unknown): unknown[] {
  if (!isRecord(value)) return [value];
  const roots: unknown[] = [value];
  for (const key of OUTPUT_WRAPPER_KEYS) {
    const nested = value[key];
    if (nested !== undefined) roots.push(nested);
  }
  return roots;
}

function recordItems(value: unknown[]): Record<string, unknown>[] {
  return value.filter(isRecord);
}

function normalizeSourceCandidate(
  candidate: Record<string, unknown>,
  context: SourceMetadata,
  callId: string,
  index: number,
): AggregatedToolSource | null {
  const title = readString(candidate, TITLE_KEYS);
  if (!title) return null;

  const metadata = sourceMetadata(candidate);
  const url = safeExternalUrl(readString(candidate, URL_KEYS));
  const snippet = readString(candidate, SNIPPET_KEYS);
  const score = readFiniteNumber(candidate, SCORE_KEYS);
  return {
    id: `${callId}:${index}`,
    title,
    sourceType: metadata.sourceType ?? context.sourceType,
    providerLabel: metadata.providerLabel ?? context.providerLabel,
    ...(url ? { url } : {}),
    ...(snippet ? { snippet } : {}),
    ...(score !== null ? { score } : {}),
  };
}

function deduplicateSources(
  perCallSources: readonly (readonly AggregatedToolSource[])[],
): AggregatedToolSource[] {
  const seen = new Set<string>();
  const sources: AggregatedToolSource[] = [];
  for (const callSources of perCallSources) {
    for (const source of callSources) {
      const key = source.url
        ? canonicalUrlKey(source.url)
        : [
            'source',
            source.providerLabel?.toLocaleLowerCase() ?? '',
            source.sourceType?.toLocaleLowerCase() ?? '',
            source.title.toLocaleLowerCase(),
          ].join(':');
      if (seen.has(key)) continue;
      seen.add(key);
      sources.push(source);
    }
  }
  return sources;
}

function groupSources(sources: readonly AggregatedToolSource[]): AggregatedToolSourceGroup[] {
  const groups = new Map<string, AggregatedToolSourceGroup>();
  for (const source of sources) {
    const domain = source.url ? urlDomain(source.url) : null;
    const key = domain
      ? `web:${domain}`
      : source.providerLabel
        ? `provider:${source.providerLabel.toLocaleLowerCase()}`
        : source.sourceType
          ? `type:${source.sourceType.toLocaleLowerCase()}`
          : 'other';
    const label = domain ?? source.providerLabel ?? source.sourceType;
    const group = groups.get(key);
    if (group) {
      group.sources.push(source);
    } else {
      groups.set(key, { key, label, sources: [source] });
    }
  }
  return [...groups.values()];
}

function parseStructuredOutput(value: unknown): unknown | null {
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return null;
  }
}

function safeExternalUrl(value: string | null): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    const hostname = url.hostname.toLocaleLowerCase();
    const loopback =
      hostname === 'localhost' ||
      hostname === '127.0.0.1' ||
      hostname === '[::1]' ||
      hostname === '::1';
    if (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback)) {
      return undefined;
    }
    url.hash = '';
    return url.toString();
  } catch {
    return undefined;
  }
}

function canonicalUrlKey(value: string): string {
  const url = new URL(value);
  const hostname = url.hostname.toLocaleLowerCase().replace(/^www\./u, '');
  const pathname =
    url.pathname.length > 1 && url.pathname.endsWith('/')
      ? url.pathname.slice(0, -1)
      : url.pathname;
  return `${url.protocol}//${hostname}${url.port ? `:${url.port}` : ''}${pathname}${url.search}`;
}

function urlDomain(value: string): string {
  return new URL(value).hostname.toLocaleLowerCase().replace(/^www\./u, '');
}

function readString(
  value: Record<string, unknown>,
  keys: readonly string[],
): string | null {
  for (const key of keys) {
    const candidate = value[key];
    if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
  }
  return null;
}

function readFiniteNumber(
  value: Record<string, unknown>,
  keys: readonly string[],
): number | null {
  for (const key of keys) {
    const candidate = value[key];
    if (typeof candidate === 'number' && Number.isFinite(candidate)) return candidate;
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
