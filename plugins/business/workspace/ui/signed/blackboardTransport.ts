import type {} from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { uploadBoardFile, downloadBoardFile } from './boardFiles';
import { readDirectory } from './readDirectory';

type Wire = { data: unknown; status: number; headers: Record<string, string> };
const itemRoutes = [
  /^(blackboard\/posts)\/([^/]+)(\/replies|\/pin|\/unpin)?$/,
  /^(blackboard\/posts)\/([^/]+)\/replies\/([^/]+)$/,
  /^(members|agents|genes|topology\/nodes|topology\/edges)\/([^/]+)$/,
  /^(objectives)\/([^/]+)(\/project-to-task)?$/,
  /^(tasks)\/([^/]+)(\/experience|\/execution-session|\/assign-agent|\/unassign-agent|\/recovery-actions)?$/,
  /^(plan\/outbox)\/([^/]+)(\/retry)$/,
  /^(plan\/nodes)\/([^/]+)(\/request-replan|\/reopen|\/accept-review)$/,
  /^(blackboard\/files)\/(?!mkdir$|upload$)([^/]+)(\/copy|\/download)?$/,
];

export async function request(path: string, init: RequestInit = {}) {
  const host = window.memstack;
  const context = await host.getContext();
  const url = new URL(path, 'https://workspace.invalid');
  const pathname = url.pathname.replace(/^\/api\/v1\//, '/');
  const base =
    '/tenants/' +
    encodeURIComponent(context.tenantId) +
    '/projects/' +
    encodeURIComponent(context.projectId!) +
    '/workspaces';
  if (pathname === base && (!init.method || init.method === 'GET')) {
    return Response.json(await readDirectory(host, init.signal ?? undefined));
  }
  const prefix = pathname.startsWith(base + '/') ? base : '/workspaces';
  if (!pathname.startsWith(prefix + '/')) throw Error('workspace_scope_mismatch');
  const [workspace_id, ...parts] = pathname.slice(prefix.length + 1).split('/');
  let resource = parts.join('/');
  const ids: string[] = [];
  for (const pattern of itemRoutes) {
    const match = pattern.exec(resource);
    if (!match) continue;
    ids.push(decodeURIComponent(match[2]));
    if (resource.includes('/replies/') && match[3]) {
      resource = match[1] + '/:id/replies/:id';
      ids.push(decodeURIComponent(match[3]));
    } else resource = match[1] + '/:id' + (match[3] ?? '');
    break;
  }
  const params = {
    workspace_id: decodeURIComponent(workspace_id),
    resource,
    ids,
    query: Object.fromEntries(url.searchParams),
  };
  const method = init.method ?? 'GET';
  const options = { signal: init.signal ?? undefined };
  let result: Wire;
  if (method === 'GET' && resource === 'blackboard/files/:id/download')
    return downloadBoardFile(params.workspace_id, ids[0], options.signal);
  if (method === 'GET') result = (await host.invoke('blackboard-read', params, options)) as Wire;
  else {
    const headers = new Headers(init.headers);
    const fields = typeof init.body === 'string' ? JSON.parse(init.body) : undefined;
    const expected = headers.get('X-Expected-Revision') ?? fields?.expected_revision;
    const revision =
      expected === undefined || expected === null
        ? (
            (await host.invoke(
              'blackboard-read',
              { workspace_id, resource: 'collaboration/authority' },
              options
            )) as { data: { revision: number } }
          ).data.revision
        : Number(expected);
    const requestId =
      headers.get('Idempotency-Key') ?? fields?.idempotency_key ?? crypto.randomUUID();
    if (init.body instanceof FormData)
      result = await uploadBoardFile({
        workspace: params.workspace_id,
        revision,
        requestId,
        form: init.body,
        native: resource === 'collaboration/mutations/files/upload',
        signal: options.signal,
      });
    else
      result = (await host.invoke(
        'blackboard-change',
        {
          ...params,
          method,
          fields,
          revision,
          request_id: requestId,
        },
        options
      )) as Wire;
  }
  return new Response(result.status === 204 ? null : JSON.stringify(result.data), {
    status: result.status,
    headers: { ...result.headers, 'Content-Type': 'application/json' },
  });
}

type Consumer<T> = (response: Response) => T;
function read<T>(path: string, consumer: Consumer<T>) {
  return request(path).then(consumer);
}
function mutation(method: string) {
  return <T>(path: string, body: unknown, consumer: Consumer<T>) =>
    request(path, { method, body: JSON.stringify(body) }).then(consumer);
}
export const apiFetch = {
  get: read,
  post: mutation('POST'),
  patch: mutation('PATCH'),
  put: mutation('PUT'),
  delete: <T>(path: string, consumer: Consumer<T>) =>
    request(path, { method: 'DELETE' }).then(consumer),
};
export function desktopApiFetch(_: unknown, path: string, init: RequestInit) {
  return request(path, init);
}

type HttpOptions = { params?: Record<string, string>; signal?: AbortSignal; responseType?: string };
async function http(method: string, path: string, body: unknown, opt?: HttpOptions) {
  const url = new URL(path, 'https://workspace.invalid');
  for (const [key, value] of Object.entries(opt?.params ?? {})) url.searchParams.set(key, value);
  const response = await request(url.pathname + url.search, {
    method,
    body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
    signal: opt?.signal,
  });
  if (response.status === 204) return;
  return opt?.responseType === 'blob' ? response.blob() : response.json();
}
export const httpClient = {
  get: (p: string, o?: HttpOptions) => http('GET', p, undefined, o),
  post: (p: string, d?: unknown, o?: HttpOptions) => http('POST', p, d, o),
  patch: (p: string, d?: unknown, o?: HttpOptions) => http('PATCH', p, d, o),
  put: (p: string, d?: unknown, o?: HttpOptions) => http('PUT', p, d, o),
  delete: (p: string, o?: HttpOptions) => http('DELETE', p, undefined, o),
};
