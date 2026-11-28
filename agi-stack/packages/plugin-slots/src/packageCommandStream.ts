export async function readPackageCommandStream(
  response: Response,
  onEvent: (value: unknown) => void,
  onActivity?: () => void,
): Promise<unknown> {
  if (!response.ok || !response.body || response.headers.get('Content-Type')?.split(';')[0] !== 'application/x-ndjson')
    throw new Error('package_stream_unavailable');
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let buffer = '';
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split('\n');
      buffer = done ? '' : lines.pop()!;
      for (const line of lines) {
        if (!line.trim()) continue;
        if (line.length > 1024 * 1024) throw new Error('package_stream_record_limit');
        const record = JSON.parse(line);
        if (record.type === 'result') return record.data;
        if (record.type === 'error') throw new Error(typeof record.detail === 'string' ? record.detail : 'page_request_failed');
        if (record.type === 'progress') onEvent(record.data);
        else if (record.type !== 'keepalive') throw new Error('package_stream_invalid');
        onActivity?.();
      }
      if (done) throw new Error('package_stream_incomplete');
      if (buffer.length > 1024 * 1024) throw new Error('package_stream_record_limit');
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
