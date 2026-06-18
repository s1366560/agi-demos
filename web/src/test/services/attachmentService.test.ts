import { describe, expect, it, vi, beforeEach } from 'vitest';

import { clearAuthState, getAuthToken } from '@/utils/tokenResolver';

import { httpClient } from '../../services/client/httpClient';
import { attachmentService, type AttachmentResponse } from '../../services/attachmentService';

vi.mock('@/utils/tokenResolver', () => ({
  getAuthToken: vi.fn(),
  clearAuthState: vi.fn(),
}));

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
    upload: vi.fn(),
  },
}));

describe('attachmentService', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    vi.mocked(getAuthToken).mockReturnValue('token-1');
  });

  const completedAttachment: AttachmentResponse = {
    id: 'attachment-1',
    conversation_id: 'conversation-1',
    project_id: 'project-1',
    filename: 'large.bin',
    mime_type: 'application/octet-stream',
    size_bytes: 10,
    purpose: 'both',
    status: 'uploaded',
    created_at: '2026-01-01T00:00:00Z',
  };

  it('uses multipart upload transport when aborting multipart uploads', async () => {
    vi.mocked(httpClient.upload).mockResolvedValueOnce({ success: true });

    await attachmentService.abortUpload('attachment-1');

    expect(httpClient.upload).toHaveBeenCalledTimes(1);
    const [path, formData] = vi.mocked(httpClient.upload).mock.calls[0];
    expect(path).toBe('/attachments/upload/abort');
    expect(formData).toBeInstanceOf(FormData);
    expect(formData.get('attachment_id')).toBe('attachment-1');
    expect(httpClient.post).not.toHaveBeenCalled();
  });

  it('uses centralized API URL and locale-aware auth headers for part uploads', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify({ part_number: 1, etag: 'etag-1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await attachmentService.uploadPart(
      'attachment-1',
      1,
      new Blob(['chunk'], { type: 'application/octet-stream' })
    );

    expect(result).toEqual({ part_number: 1, etag: 'etag-1' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/attachments/upload/part');
    expect(init.method).toBe('POST');
    expect(init.headers).toEqual(
      expect.objectContaining({
        Authorization: 'Bearer token-1',
        'Accept-Language': expect.any(String),
        'X-Language': expect.any(String),
      })
    );
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get('attachment_id')).toBe('attachment-1');
  });

  it('clears auth state when part uploads receive unauthorized responses', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Token expired' }), {
        status: 401,
        statusText: 'Unauthorized',
        headers: { 'Content-Type': 'application/json' },
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      attachmentService.uploadPart(
        'attachment-1',
        1,
        new Blob(['chunk'], { type: 'application/octet-stream' })
      )
    ).rejects.toThrow('Token expired');

    expect(clearAuthState).toHaveBeenCalledTimes(1);
  });

  it('uses centralized API URL and clears auth state for simple uploads', async () => {
    const requests: MockUploadRequest[] = [];

    class MockUploadRequest {
      readonly upload = { addEventListener: vi.fn() };
      readonly headers = new Map<string, string>();
      private readonly listeners = new Map<string, EventListenerOrEventListenerObject>();
      method = '';
      url = '';
      status = 401;
      statusText = 'Unauthorized';
      responseText = JSON.stringify({ detail: 'Upload token expired' });

      constructor() {
        requests.push(this);
      }

      addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
        this.listeners.set(type, listener);
      }

      open(method: string, url: string): void {
        this.method = method;
        this.url = url;
      }

      setRequestHeader(key: string, value: string): void {
        this.headers.set(key, value);
      }

      send(_body: FormData): void {
        const loadListener = this.listeners.get('load');
        const event = new Event('load');
        if (typeof loadListener === 'function') {
          loadListener(event);
        } else {
          loadListener?.handleEvent(event);
        }
      }
    }

    vi.stubGlobal('XMLHttpRequest', MockUploadRequest);

    await expect(
      attachmentService.uploadSimple(
        'conversation-1',
        'project-1',
        new File(['hello'], 'hello.txt', { type: 'text/plain' })
      )
    ).rejects.toThrow('Upload token expired');

    expect(requests).toHaveLength(1);
    expect(requests[0].method).toBe('POST');
    expect(requests[0].url).toBe('/api/v1/attachments/upload/simple');
    expect(Object.fromEntries(requests[0].headers)).toEqual(
      expect.objectContaining({
        Authorization: 'Bearer token-1',
        'Accept-Language': expect.any(String),
        'X-Language': expect.any(String),
      })
    );
    expect(clearAuthState).toHaveBeenCalledTimes(1);
  });

  it('uses the backend-provided multipart part size when slicing files', async () => {
    vi.spyOn(attachmentService, 'initiateUpload').mockResolvedValueOnce({
      attachmentId: 'attachment-1',
      uploadId: 'upload-1',
      totalParts: 3,
      partSize: 4,
    });
    const uploadPartSpy = vi
      .spyOn(attachmentService, 'uploadPart')
      .mockImplementation(async (_attachmentId, partNumber, data) => ({
        part_number: partNumber,
        etag: `etag-${partNumber}-${data.size}`,
      }));
    const completeSpy = vi
      .spyOn(attachmentService, 'completeUpload')
      .mockResolvedValueOnce(completedAttachment);

    const file = new File([new Uint8Array(10)], 'large.bin', {
      type: 'application/octet-stream',
    });
    const progress = vi.fn();

    const result = await attachmentService.uploadMultipart(
      'conversation-1',
      'project-1',
      file,
      'both',
      progress
    );

    expect(result).toBe(completedAttachment);
    expect(uploadPartSpy).toHaveBeenCalledTimes(3);
    expect(uploadPartSpy.mock.calls.map(([, partNumber, blob]) => [partNumber, blob.size])).toEqual(
      [
        [1, 4],
        [2, 4],
        [3, 2],
      ]
    );
    expect(completeSpy).toHaveBeenCalledWith('attachment-1', [
      { part_number: 1, etag: 'etag-1-4' },
      { part_number: 2, etag: 'etag-2-4' },
      { part_number: 3, etag: 'etag-3-2' },
    ]);
    expect(progress).toHaveBeenLastCalledWith({
      loaded: 10,
      total: 10,
      percentage: 100,
    });
  });

  it('aborts multipart uploads when the initiate response is invalid', async () => {
    vi.spyOn(attachmentService, 'initiateUpload').mockResolvedValueOnce({
      attachmentId: 'attachment-1',
      uploadId: 'upload-1',
      totalParts: 2,
      partSize: 0,
    });
    const abortSpy = vi.spyOn(attachmentService, 'abortUpload').mockResolvedValueOnce();
    const uploadPartSpy = vi.spyOn(attachmentService, 'uploadPart');

    const file = new File([new Uint8Array(10)], 'large.bin', {
      type: 'application/octet-stream',
    });

    await expect(
      attachmentService.uploadMultipart('conversation-1', 'project-1', file)
    ).rejects.toThrow('Invalid upload session');

    expect(abortSpy).toHaveBeenCalledWith('attachment-1');
    expect(uploadPartSpy).not.toHaveBeenCalled();
  });

  it('builds download URLs through the shared API URL helper', () => {
    expect(attachmentService.getDownloadUrl('attachment-1')).toBe(
      '/api/v1/attachments/attachment-1/download'
    );
  });
});
