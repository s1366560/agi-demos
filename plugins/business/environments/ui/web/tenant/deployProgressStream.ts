import { apiFetch } from '@/services/client/urlUtils';
import type { WebOperationContextV2 } from '@/plugins/webOperationAdmissionV2';

export interface DeployProgressSseEvent {
  type: string;
  status?: string | undefined;
  deploy_id?: string | undefined;
}

interface DeployProgressStreamOptions {
  parent?: WebOperationContextV2;
  deployId: string;
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

function findEventSeparator(buffer: string): { index: number; length: number } | null {
  const lfIndex = buffer.indexOf('\n\n');
  const crlfIndex = buffer.indexOf('\r\n\r\n');

  if (lfIndex === -1 && crlfIndex === -1) {
    return null;
  }
  if (lfIndex === -1) {
    return { index: crlfIndex, length: 4 };
  }
  if (crlfIndex === -1) {
    return { index: lfIndex, length: 2 };
  }
  return crlfIndex < lfIndex ? { index: crlfIndex, length: 4 } : { index: lfIndex, length: 2 };
}

export async function streamDeployProgress({
  deployId,
  signal,
  onEvent,
  parent,
}: DeployProgressStreamOptions): Promise<void> {
  return apiFetch.get(
    `/deploys/${encodeURIComponent(deployId)}/progress`,
    async (response, operation) => {
      operation.check();

      if (!response.body) {
        throw new Error('Deploy progress stream response has no body');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      const consumeEvent = async (rawEvent: string): Promise<boolean> => {
        operation.check();
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

      try {
        while (!operation.signal.aborted) {
          const { done, value } = await reader.read();
          operation.check();
          if (done) {
            break;
          }

          buffer += decoder.decode(value, { stream: true });
          let separator = findEventSeparator(buffer);
          while (separator) {
            const rawEvent = buffer.slice(0, separator.index);
            buffer = buffer.slice(separator.index + separator.length);
            if (await consumeEvent(rawEvent)) {
              return;
            }
            separator = findEventSeparator(buffer);
          }
        }

        operation.check();
        buffer += decoder.decode();
        if (buffer.trim()) {
          await consumeEvent(buffer);
        }
      } finally {
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
      }
    },
    {
      headers: {
        Accept: 'text/event-stream',
      },
      signal,
      ...(parent ? { parent } : {}),
    }
  );
}
