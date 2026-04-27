import { fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SharedFileBrowser } from '@/components/blackboard/tabs/SharedFileBrowser';
import { render, screen } from '@/test/utils';

import type { BlackboardFileItem } from '@/services/blackboardFileService';

const {
  listFilesMock,
  createDirectoryMock,
  uploadFileMock,
  downloadFileMock,
  deleteFileMock,
  messageSuccessMock,
  messageErrorMock,
} = vi.hoisted(() => ({
  listFilesMock: vi.fn(),
  createDirectoryMock: vi.fn(),
  uploadFileMock: vi.fn(),
  downloadFileMock: vi.fn(),
  deleteFileMock: vi.fn(),
  messageSuccessMock: vi.fn(),
  messageErrorMock: vi.fn(),
}));

vi.mock('@/services/blackboardFileService', () => ({
  blackboardFileService: {
    listFiles: (...args: unknown[]) => listFilesMock(...args),
    createDirectory: (...args: unknown[]) => createDirectoryMock(...args),
    uploadFile: (...args: unknown[]) => uploadFileMock(...args),
    downloadFile: (...args: unknown[]) => downloadFileMock(...args),
    deleteFile: (...args: unknown[]) => deleteFileMock(...args),
  },
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  useLazyMessage: () => ({
    success: messageSuccessMock,
    error: messageErrorMock,
  }),
}));

function makeFile(overrides: Partial<BlackboardFileItem> = {}): BlackboardFileItem {
  return {
    id: 'file-1',
    workspace_id: 'ws-1',
    parent_path: '/',
    name: 'notes.txt',
    is_directory: false,
    file_size: 12,
    content_type: 'text/plain',
    uploader_type: 'user',
    uploader_id: 'user-1',
    uploader_name: 'User One',
    created_at: '2026-04-27T00:00:00Z',
    ...overrides,
  };
}

describe('SharedFileBrowser', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    listFilesMock.mockResolvedValue([]);
    createDirectoryMock.mockResolvedValue(makeFile({ id: 'dir-1', is_directory: true }));
    uploadFileMock.mockResolvedValue(makeFile());
    downloadFileMock.mockResolvedValue(new Blob(['hello'], { type: 'text/plain' }));
    deleteFileMock.mockResolvedValue(true);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
  });

  it('marks the file browser as an owned authoritative surface', async () => {
    render(<SharedFileBrowser tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    await waitFor(() => {
      expect(listFilesMock).toHaveBeenCalledWith('t-1', 'p-1', 'ws-1', '/');
    });

    const boundaryBadge = screen.getByText('blackboard.filesSurfaceHint').closest('div');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-boundary', 'owned');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-authority', 'authoritative');
  });

  it('navigates into directories with canonical child paths', async () => {
    listFilesMock
      .mockResolvedValueOnce([makeFile({ id: 'dir-1', name: 'docs', is_directory: true })])
      .mockResolvedValueOnce([]);

    render(<SharedFileBrowser tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    fireEvent.click(await screen.findByText('docs'));

    await waitFor(() => {
      expect(listFilesMock).toHaveBeenLastCalledWith('t-1', 'p-1', 'ws-1', '/docs/');
    });
  });

  it('creates folders in the active path and refreshes the listing', async () => {
    render(<SharedFileBrowser tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    fireEvent.click(screen.getByRole('button', { name: 'blackboard.files.newFolder' }));
    fireEvent.change(screen.getByLabelText('blackboard.files.folderName'), {
      target: { value: 'docs' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'blackboard.files.create' }));

    await waitFor(() => {
      expect(createDirectoryMock).toHaveBeenCalledWith('t-1', 'p-1', 'ws-1', '/', 'docs');
    });
    expect(listFilesMock).toHaveBeenCalledTimes(2);
    expect(messageSuccessMock).toHaveBeenCalled();
  });

  it('uploads every selected file and refreshes once', async () => {
    const { container } = render(
      <SharedFileBrowser tenantId="t-1" projectId="p-1" workspaceId="ws-1" />
    );
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    const first = new File(['a'], 'a.txt', { type: 'text/plain' });
    const second = new File(['b'], 'b.txt', { type: 'text/plain' });

    fireEvent.change(input!, { target: { files: [first, second] } });

    await waitFor(() => {
      expect(uploadFileMock).toHaveBeenCalledTimes(2);
    });
    expect(uploadFileMock).toHaveBeenNthCalledWith(1, 't-1', 'p-1', 'ws-1', '/', first);
    expect(uploadFileMock).toHaveBeenNthCalledWith(2, 't-1', 'p-1', 'ws-1', '/', second);
    expect(listFilesMock).toHaveBeenCalledTimes(2);
  });

  it('deletes files only after confirmation', async () => {
    listFilesMock.mockResolvedValueOnce([makeFile()]);
    render(<SharedFileBrowser tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    fireEvent.click(await screen.findByTitle('blackboard.files.delete'));

    await waitFor(() => {
      expect(deleteFileMock).toHaveBeenCalledWith('t-1', 'p-1', 'ws-1', 'file-1');
    });
    expect(window.confirm).toHaveBeenCalled();
    expect(listFilesMock).toHaveBeenCalledTimes(2);
  });

  it('surfaces load failures with a retry action', async () => {
    listFilesMock.mockRejectedValueOnce(new Error('load exploded')).mockResolvedValueOnce([]);

    render(<SharedFileBrowser tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    expect(await screen.findByRole('alert')).toHaveTextContent('load exploded');

    fireEvent.click(screen.getByRole('button', { name: /common.retry/i }));

    await waitFor(() => {
      expect(listFilesMock).toHaveBeenCalledTimes(2);
    });
  });
});
