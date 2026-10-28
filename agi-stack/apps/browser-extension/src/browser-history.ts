import type { ChromeApi } from './chrome-api';
import { ErrorCodes, RpcError } from './protocol';

interface HistoryApi {
  search(query: { text: string; startTime: number; endTime: number; maxResults: number }): Promise<Array<{ url?: string; title?: string }>>;
  getVisits(query: { url: string }): Promise<Array<{ visitId: string; visitTime?: number }>>;
}

/** Read actual visit timestamps; repeated visits remain separate history entries. */
export function createHistoryHandler(chrome: ChromeApi) {
  return async (input: unknown) => {
    if (!input || typeof input !== 'object' || Array.isArray(input)) throw new RpcError(ErrorCodes.invalidParams, 'history options must be an object');
    const options = input as Record<string, unknown>;
    if (Object.keys(options).some(key => !['from', 'to', 'limit', 'queries'].includes(key))) throw new RpcError(ErrorCodes.invalidParams, 'unknown history option');
    const date = (value: unknown, fallback: number) => {
      const time = value === undefined ? fallback : typeof value === 'string' ? Date.parse(value) : NaN;
      if (!Number.isFinite(time) || time < 0) throw new RpcError(ErrorCodes.invalidParams, 'invalid history date');
      return time;
    };
    const startTime = date(options.from, 0);
    const endTime = date(options.to, Date.now());
    const limit = options.limit ?? 100;
    const queries = options.queries ?? [''];
    if (startTime > endTime || !Number.isSafeInteger(limit) || Number(limit) < 1 || Number(limit) > 1000) throw new RpcError(ErrorCodes.invalidParams, 'invalid history range or limit');
    if (!Array.isArray(queries) || queries.length > 8 || queries.some(query => typeof query !== 'string' || query.length > 1024)) throw new RpcError(ErrorCodes.invalidParams, 'invalid history queries');
    const history = (chrome as unknown as { history?: HistoryApi }).history;
    if (!history) throw new RpcError(ErrorCodes.methodNotFound, 'browser history permission is unavailable');
    const urls = new Map<string, string | undefined>();
    for (const text of queries.length ? queries : ['']) {
      for (const item of await history.search({ text, startTime, endTime, maxResults: Number(limit) })) {
        if (item.url) urls.set(item.url, item.title);
      }
    }
    const visits: Array<{ dateVisited: string; title?: string; url: string }> = [];
    for (const [url, title] of urls) {
      for (const visit of await history.getVisits({ url })) {
        if (visit.visitTime !== undefined && visit.visitTime >= startTime && visit.visitTime <= endTime) visits.push({ dateVisited: new Date(visit.visitTime).toISOString(), title, url });
      }
    }
    return visits.sort((a, b) => b.dateVisited.localeCompare(a.dateVisited)).slice(0, Number(limit));
  };
}
