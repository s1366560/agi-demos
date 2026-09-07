import { RuntimeV2Error } from '@agistack/plugin-runtime';
import {
  STRUCTURED_IMAGE_PREVIEW_MAX_BYTES_V2,
  imagePreviewErrorV2,
  isImageMimeV2,
  requireStructuredImagePreviewBlobV2,
  resolveStructuredImagePreviewUrlV2,
  validateImagePreviewUrlV2,
  type PreparedStructuredImagePreviewV2,
} from './desktopStructuredImagePreviewContractV2';

export async function loadStructuredImagePreviewHttpV2(
  input: PreparedStructuredImagePreviewV2,
): Promise<Blob> {
  const signal = input.signal;
  signal.throwIfAborted();
  const url = resolveStructuredImagePreviewUrlV2(input);
  let body: ReadableStream<Uint8Array> | null = null;
  try {
    const response = await fetch(url, {
      method: 'GET',
      cache: 'no-store',
      credentials: 'omit',
      referrerPolicy: 'no-referrer',
      signal,
    });
    body = response.body;
    signal.throwIfAborted();
    if (!response.ok) throw imagePreviewErrorV2('http_failed');
    if (response.url) validateImagePreviewUrlV2(response.url);
    const mimeType = response.headers.get('content-type') ?? '';
    const lengthHeader = response.headers.get('content-length');
    if (!isImageMimeV2(mimeType)) throw imagePreviewErrorV2('content_invalid');
    if (lengthHeader !== null && Number(lengthHeader) > STRUCTURED_IMAGE_PREVIEW_MAX_BYTES_V2)
      throw imagePreviewErrorV2('content_too_large');
    const reader = response.body?.getReader();
    if (!reader) return requireStructuredImagePreviewBlobV2(new Blob([], { type: mimeType }));
    const chunks: Uint8Array<ArrayBuffer>[] = [];
    let total = 0;
    let settled = false;
    const abort = () => {
      void reader.cancel().catch(() => undefined);
    };
    signal.addEventListener('abort', abort, { once: true });
    try {
      for (;;) {
        signal.throwIfAborted();
        const { value, done } = await reader.read();
        signal.throwIfAborted();
        if (done) {
          settled = true;
          break;
        }
        total += value.byteLength;
        if (total > STRUCTURED_IMAGE_PREVIEW_MAX_BYTES_V2)
          throw imagePreviewErrorV2('content_too_large');
        chunks.push(new Uint8Array(value));
      }
      return requireStructuredImagePreviewBlobV2(new Blob(chunks, { type: mimeType }));
    } finally {
      signal.removeEventListener('abort', abort);
      if (!settled) await reader.cancel().catch(() => undefined);
      reader.releaseLock();
    }
  } catch (error) {
    if (body && !body.locked) await body.cancel().catch(() => undefined);
    signal.throwIfAborted();
    // Network failures may contain signed URLs; only structural reason codes leave this transport.
    if (error instanceof RuntimeV2Error) throw error;
    throw imagePreviewErrorV2('transport_failed');
  }
}
