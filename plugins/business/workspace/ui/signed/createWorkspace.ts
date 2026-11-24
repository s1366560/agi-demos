import type { RichPageRuntime } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';

export function workspaceCreation(host: RichPageRuntime) {
  let previousBody: string | undefined;
  let requestId: string;
  return async (data: { name: string; description?: string }, signal?: AbortSignal) => {
    const body = JSON.stringify(data);
    if (body !== previousBody) {
      previousBody = body;
      requestId = crypto.randomUUID();
    }
    return (await host.invoke(
      'create-workspace',
      { ...data, request_id: requestId },
      { signal }
    )) as { id: string };
  };
}

export function projectDirectory(tenant: string, project: string | null) {
  if (!project) throw new Error('project_required');
  return (
    '/tenant/' +
    encodeURIComponent(tenant) +
    '/project/' +
    encodeURIComponent(project) +
    '/workspaces'
  );
}
