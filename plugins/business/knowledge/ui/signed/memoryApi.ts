import type {} from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import type { MemoryListResponse, Memory, MemoryUpdate } from '../../../../../web/src/types/memory';

const host = window.memstack;
let previous: string | undefined;
let requestId: string;
export const memoryAPI = {
  list(_project: string, query: Record<string, unknown>) {
    return host.invoke('list-memories', query) as Promise<MemoryListResponse>;
  },
  get(_project: string, id: string) {
    return host.invoke('read-memory', { id, detail: true }) as Promise<Memory>;
  },
  async update(_project: string, id: string, data: MemoryUpdate) {
    const payload = { id, ...data };
    const body = JSON.stringify(payload);
    if (body !== previous) {
      previous = body;
      requestId = crypto.randomUUID();
    }
    return host.invoke('save-memory', { ...payload, change_id: requestId }) as Promise<Memory>;
  },
};
