import type {} from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import type { MemoryListResponse, Memory, MemoryUpdate } from '../../../../../web/src/types/memory';

const host = window.memstack;
let previous: string | undefined;
let requestId: string;
export const memoryAPI = {
  delete(_project: string, id: string, version: number) {
    return host.invoke('delete-memory', { id, version, change_id: crypto.randomUUID() });
  },
  reprocess(_project: string, id: string) {
    return host.invoke('reindex-memory', { id });
  },
  create(
    _project: string,
    data: { title: string; content: string; tags: string[]; metadata: object },
  ) {
    return host.invoke('save-memory', {
      title: data.title,
      content: data.content,
      tags: data.tags,
      metadata: data.metadata,
      version: 0,
      change_id: crypto.randomUUID(),
    }) as Promise<Memory & { task_id?: string }>;
  },
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
