import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { sandboxUploadService } from '@/services/sandboxUploadService';

import { message } from '@/components/ui/lazyAntd';

import { useFileUpload } from '@/components/agent/FileUploader';

vi.mock('@/services/sandboxUploadService', () => ({
  sandboxUploadService: {
    upload: vi.fn(),
  },
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  message: {
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

const makeFileList = (files: File[]): FileList =>
  ({
    length: files.length,
    item: (index: number) => files[index] ?? null,
    ...Object.fromEntries(files.map((file, index) => [index, file])),
  }) as unknown as FileList;

describe('useFileUpload', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('does not add a permanently uploading chip when project context is missing', () => {
    const { result } = renderHook(() => useFileUpload({ projectId: undefined }));
    const file = new File(['hello'], 'hello.txt', { type: 'text/plain' });

    act(() => {
      result.current.addFiles(makeFileList([file]));
    });

    expect(result.current.attachments).toEqual([]);
    expect(sandboxUploadService.upload).not.toHaveBeenCalled();
    expect(message.error).toHaveBeenCalledWith('Cannot upload: missing project context');
  });

  it('marks files uploaded when sandbox upload succeeds', async () => {
    vi.mocked(sandboxUploadService.upload).mockResolvedValueOnce({
      success: true,
      sandbox_path: '/workspace/hello.txt',
      size_bytes: 5,
    });
    const { result } = renderHook(() => useFileUpload({ projectId: 'project-1' }));
    const file = new File(['hello'], 'hello.txt', { type: 'text/plain' });

    act(() => {
      result.current.addFiles(makeFileList([file]));
    });

    await waitFor(() => {
      expect(result.current.attachments[0]?.status).toBe('uploaded');
    });

    expect(result.current.attachments[0]?.fileMetadata).toEqual({
      filename: 'hello.txt',
      sandbox_path: '/workspace/hello.txt',
      mime_type: 'text/plain',
      size_bytes: 5,
    });
  });
});
