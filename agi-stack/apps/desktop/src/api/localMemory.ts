import type { LocalMemoryResult } from '../types';

type TauriInvoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

function invoke(): TauriInvoke | undefined {
  return window.__TAURI__?.core?.invoke;
}

function requireDesktopInvoke(): TauriInvoke {
  const tauriInvoke = invoke();
  if (!tauriInvoke) {
    throw new Error('Local memory commands require the Tauri desktop shell.');
  }
  return tauriInvoke;
}

export async function ingestLocalMemory(
  projectId: string,
  authorId: string,
  content: string,
): Promise<LocalMemoryResult> {
  const tauriInvoke = requireDesktopInvoke();
  const value = await tauriInvoke('ingest', { projectId, authorId, content });
  return { label: 'Ingest', usedFallback: false, data: parseJsonResult(value) };
}

export async function searchLocalMemory(
  projectId: string,
  q: string,
  limit: number,
): Promise<LocalMemoryResult> {
  const tauriInvoke = requireDesktopInvoke();
  const value = await tauriInvoke('search', { projectId, q, limit });
  return { label: 'Keyword search', usedFallback: false, data: parseJsonResult(value) };
}

export async function semanticSearchLocalMemory(
  projectId: string,
  q: string,
  limit: number,
): Promise<LocalMemoryResult> {
  const tauriInvoke = requireDesktopInvoke();
  const value = await tauriInvoke('semantic_search', { projectId, q, limit });
  return { label: 'Semantic search', usedFallback: false, data: parseJsonResult(value) };
}

function parseJsonResult(value: unknown): unknown {
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}
