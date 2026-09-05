import { installResourceOperationFixtureV2 } from './webResourceOperationFixtureV2';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('@/services/client/urlUtils', () => ({
  apiFetch: {
    get: vi.fn(),
  },
}));

import { fetchArtifactResource } from '@/services/artifactService';
import { apiFetch } from '@/services/client/urlUtils';

describe('artifactService', () => {
  let fixture: ReturnType<typeof installResourceOperationFixtureV2>;
  afterEach(async () => {
    await fixture.close();
    vi.unstubAllGlobals();
  });
  beforeEach(() => {
    vi.clearAllMocks();
    fixture = installResourceOperationFixtureV2();
  });

  it('uses apiFetch for local artifact API URLs', async () => {
    const response = new Response('artifact');
    vi.mocked(apiFetch.get).mockImplementationOnce(async (_url, consume) =>
      consume(response, { check() {} } as never)
    );

    const result = await fetchArtifactResource('/api/v1/artifacts/artifact-1/download', (body) =>
      body.text()
    );

    expect(result).toBe('artifact');
    expect(apiFetch.get).toHaveBeenCalledWith(
      '/api/v1/artifacts/artifact-1/download',
      expect.any(Function),
      undefined
    );
  });

  it('keeps presigned external URLs on plain fetch', async () => {
    const response = new Response('artifact');
    const fetchMock = vi.fn().mockResolvedValueOnce(response);
    vi.stubGlobal('fetch', fetchMock);

    const result = await fetchArtifactResource(
      'https://storage.example.com/object?signature=abc',
      (body) => body.text()
    );

    expect(result).toBe('artifact');
    expect(fetchMock).toHaveBeenCalledWith(
      'https://storage.example.com/object?signature=abc',
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
    expect(apiFetch.get).not.toHaveBeenCalled();
  });
  it('holds its lease through delayed body consumption', async () => {
    let stream!: ReadableStreamDefaultController<Uint8Array>;
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          new ReadableStream({
            start(controller) {
              stream = controller;
            },
          })
        )
      )
    );
    const result = fetchArtifactResource('https://storage.example.com/object', (response) =>
      response.text()
    );
    await vi.waitFor(() => expect(fixture.acquired()).toBe(1));
    expect(fixture.released()).toBe(0);
    stream.enqueue(new TextEncoder().encode('complete'));
    stream.close();
    expect(await result).toBe('complete');
    expect(fixture.released()).toBe(1);
  });

  it('cancels an unread response on preview-only early return', async () => {
    const cancel = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new ReadableStream({ cancel }))));
    expect(await fetchArtifactResource('https://storage.example.com/object', () => 'preview')).toBe(
      'preview'
    );
    expect(cancel).toHaveBeenCalledOnce();
    expect(fixture.released()).toBe(1);
  });
});
