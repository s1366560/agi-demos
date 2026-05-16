import { API_BASE_URL } from '@/services/client/httpClient';

export interface DeployProgressSseEvent {
  type: string;
  status?: string | undefined;
  deploy_id?: string | undefined;
}

interface DeployProgressStreamOptions {
  deployId: string;
  token: string;
  signal: AbortSignal;
  onEvent: (event: DeployProgressSseEvent) => void;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export function parseDeployProgressSseEvent(rawEvent: string): DeployProgressSseEvent | null {
  const data = rawEvent
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n')
    .trim();

  if (!data) {
    return null;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }

  if (!isRecord(parsed) || typeof parsed.type !== 'string') {
    return null;
  }

  return {
    type: parsed.type,
    status: typeof parsed.status === 'string' ? parsed.status : undefined,
    deploy_id: typeof parsed.deploy_id === 'string' ? parsed.deploy_id : undefined,
  };
}

export async function streamDeployProgress({
  deployId,
  token,
  signal,
  onEvent,
}: DeployProgressStreamOptions): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/deploys/${encodeURIComponent(deployId)}/progress`, {
    headers: {
      Accept: 'text/event-stream',
      Authorization: `Bearer ${token}`,
    },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Deploy progress stream failed with HTTP ${String(response.status)}`);
  }

  if (!response.body) {
    throw new Error('Deploy progress stream response has no body');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const consumeEvent = async (rawEvent: string): Promise<boolean> => {
    const event = parseDeployProgressSseEvent(rawEvent);
    if (!event) {
      return false;
    }

    onEvent(event);
    if (event.type === 'done') {
      await reader.cancel().catch(() => undefined);
      return true;
    }
    return false;
  };

  while (!signal.aborted) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    let separatorIndex = buffer.indexOf('\n\n');
    while (separatorIndex !== -1) {
      const rawEvent = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      if (await consumeEvent(rawEvent)) {
        return;
      }
      separatorIndex = buffer.indexOf('\n\n');
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) {
    await consumeEvent(buffer);
  }
}
