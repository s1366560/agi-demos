import { useEffect, useState } from 'react';
import type { MarketplaceTransport } from './client';

/** A result belongs only to the URL + revision that initiated it. */
export function useMarketRequest<T>(
  transport: MarketplaceTransport,
  path: string | null,
  revision: number
) {
  const [result, setResult] = useState<{
    path: string;
    revision: number;
    data?: T;
    error?: string;
  }>();
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    void transport<T>(path, { signal: controller.signal }).then(
      (data) => {
        if (!controller.signal.aborted) setResult({ path, revision, data });
      },
      (cause) => {
        if (!controller.signal.aborted) setResult({ path, revision, error: errorText(cause) });
      }
    );
    return () => controller.abort();
  }, [transport, path, revision]);
  return result?.path === path && result.revision === revision ? result : undefined;
}
export function errorText(cause: unknown) {
  return cause instanceof Error ? cause.message : String(cause);
}
export async function fileBase64(file: File) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const parts: string[] = [];
  for (let i = 0; i < bytes.length; i += 8192) {
    parts.push(String.fromCharCode(...bytes.subarray(i, i + 8192)));
  }
  return btoa(parts.join(''));
}
