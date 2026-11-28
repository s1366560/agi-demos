import type {} from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';

interface UploadOptions {
  workspace: string;
  revision: number;
  requestId: string;
  form: FormData;
  native: boolean;
  signal?: AbortSignal;
}

export async function uploadBoardFile({
  workspace,
  revision,
  requestId,
  form,
  native,
  signal,
}: UploadOptions) {
  const file = form.get('file');
  if (!(file instanceof File)) throw new Error('workspace_file_required');
  const invoke = (step: string, fields: Record<string, unknown>, cancel?: AbortSignal) =>
    window.memstack.invoke(
      'blackboard-change',
      {
        workspace_id: workspace,
        method: 'POST',
        request_id: requestId,
        revision,
        resource: 'file-transfer/' + step,
        fields,
      },
      { signal: cancel }
    );
  const size = 40 * 1024;
  await invoke(
    'begin',
    {
      filename: file.name,
      mime: file.type || 'application/octet-stream',
      size: file.size,
      parent_path: String(form.get('parent_path') ?? '/'),
    },
    signal
  );
  try {
    for (let offset = 0; offset < file.size; offset += size) {
      const bytes = new Uint8Array(await file.slice(offset, offset + size).arrayBuffer());
      await invoke('chunk', { offset, content: btoa(String.fromCharCode(...bytes)) }, signal);
    }
  } catch (error) {
    await invoke('abort', {}).catch(() => {});
    throw error;
  }
  return (await invoke(native ? 'finish-native' : 'finish', {}, signal)) as {
    status: number;
    data: unknown;
    headers: Record<string, string>;
  };
}

export async function downloadBoardFile(workspace: string, id: string, signal?: AbortSignal) {
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  const result = (await window.memstack.invoke(
    'blackboard-read',
    {
      workspace_id: workspace,
      resource: 'blackboard/files/:id/download',
      ids: [id],
    },
    {
      signal,
      onEvent(raw) {
        const { content } = raw as { content: string };
        chunks.push(Uint8Array.from(atob(content), (byte) => byte.charCodeAt(0)));
      },
    }
  )) as { mime: string; size: number };
  const blob = new Blob(chunks, { type: result.mime });
  if (blob.size !== result.size) throw new Error('workspace_file_incomplete');
  return new Response(blob);
}
