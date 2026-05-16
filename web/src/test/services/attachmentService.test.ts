import { describe, expect, it, vi, beforeEach } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { attachmentService, type AttachmentResponse } from '../../services/attachmentService';

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
});
