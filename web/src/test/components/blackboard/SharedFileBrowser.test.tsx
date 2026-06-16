import { act, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SharedFileBrowser } from '@/components/blackboard/tabs/SharedFileBrowser';
import { useWorkspaceStore } from '@/stores/workspace';
import { render, screen } from '@/test/utils';

import type { BlackboardFileItem } from '@/services/blackboardFileService';
import type { ReactNode } from 'react';

const {
  listFilesMock,
  createDirectoryMock,
  uploadFileMock,
  downloadFileMock,
  deleteFileMock,
  renameFileMock,
  moveFileMock,
  copyFileMock,
  messageSuccessMock,
  messageErrorMock,
} = vi.hoisted(() => ({
  listFilesMock: vi.fn(),
  createDirectoryMock: vi.fn(),
  uploadFileMock: vi.fn(),
  downloadFileMock: vi.fn(),
  deleteFileMock: vi.fn(),
  renameFileMock: vi.fn(),
  moveFileMock: vi.fn(),
  copyFileMock: vi.fn(),
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
    renameFile: (...args: unknown[]) => renameFileMock(...args),
    moveFile: (...args: unknown[]) => moveFileMock(...args),
    copyFile: (...args: unknown[]) => copyFileMock(...args),
  },
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyPopconfirm: ({
    children,
    okText,
    onConfirm,
  }: {
    children: ReactNode;
    okText?: ReactNode;
    onConfirm?: () => void;
  }) => (
    <span>
      {children}
      <button type="button" onClick={onConfirm}>
        {okText}
      </button>
    </span>
  ),
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
    renameFileMock.mockResolvedValue(makeFile({ name: 'renamed.txt' }));
    moveFileMock.mockResolvedValue(makeFile({ parent_path: '/docs/' }));
    copyFileMock.mockResolvedValue(makeFile({ id: 'copy-1', name: 'copy.txt' }));
    useWorkspaceStore.setState({ fileRefreshCounters: {} });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
  });

  it('marks the file browser as an owned authoritative surface', async () => {
    render(<SharedFileBrowser tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    await waitFor(() => {
      expect(listFilesMock).toHaveBeenCalledWith('t-1', 'p-1', 'ws-1', '/');
    });

    const boundaryBadge = screen.getByText('blackboard file workspace').closest('div');
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

    fireEvent.click(screen.getByRole('button', { name: 'New Folder' }));
    fireEvent.change(screen.getByLabelText('Folder name'), {
      target: { value: 'docs' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

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

    expect(input).not.toBeNull();
    if (!input) {
      throw new Error('file input not found');
    }
    fireEvent.change(input, { target: { files: [first, second] } });

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

    fireEvent.click(await screen.findByTitle('Delete'));
    fireEvent.click(await screen.findByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(deleteFileMock).toHaveBeenCalledWith('t-1', 'p-1', 'ws-1', 'file-1', false);
    });
    expect(window.confirm).not.toHaveBeenCalled();
    expect(listFilesMock).toHaveBeenCalledTimes(2);
  });

  it('renames files from the row action panel', async () => {
    listFilesMock.mockResolvedValueOnce([makeFile()]);
    render(<SharedFileBrowser tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    fireEvent.click(await screen.findByTitle('Rename'));
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'renamed.txt' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }));

    await waitFor(() => {
      expect(renameFileMock).toHaveBeenCalledWith('t-1', 'p-1', 'ws-1', 'file-1', 'renamed.txt');
    });
    expect(listFilesMock).toHaveBeenCalledTimes(2);
  });

  it('moves files to a normalized destination path', async () => {
    listFilesMock.mockResolvedValueOnce([makeFile()]);
    render(<SharedFileBrowser tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    fireEvent.click(await screen.findByTitle('Move'));
    fireEvent.change(screen.getByLabelText('Destination path'), {
      target: { value: 'docs' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Move' }));

    await waitFor(() => {
      expect(moveFileMock).toHaveBeenCalledWith('t-1', 'p-1', 'ws-1', 'file-1', '/docs/');
    });
    expect(listFilesMock).toHaveBeenCalledTimes(2);
  });

  it('copies files with a target path and name', async () => {
    listFilesMock.mockResolvedValueOnce([makeFile()]);
    render(<SharedFileBrowser tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    fireEvent.click(await screen.findByTitle('Copy'));
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'copy.txt' },
    });
    fireEvent.change(screen.getByLabelText('Destination path'), {
      target: { value: '/archive/' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

    await waitFor(() => {
      expect(copyFileMock).toHaveBeenCalledWith(
        't-1',
        'p-1',
        'ws-1',
        'file-1',
        '/archive/',
        'copy.txt'
      );
    });
    expect(listFilesMock).toHaveBeenCalledTimes(2);
  });

  it('deletes directories recursively from the row action', async () => {
    listFilesMock.mockResolvedValueOnce([
      makeFile({ id: 'dir-1', name: 'docs', is_directory: true }),
    ]);
    render(<SharedFileBrowser tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    fireEvent.click(await screen.findByTitle('Delete'));
    fireEvent.click(await screen.findByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(deleteFileMock).toHaveBeenCalledWith('t-1', 'p-1', 'ws-1', 'dir-1', true);
    });
  });

  it('surfaces load failures with a retry action', async () => {
    listFilesMock.mockRejectedValueOnce(new Error('load exploded')).mockResolvedValueOnce([]);

    render(<SharedFileBrowser tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    expect(await screen.findByRole('alert')).toHaveTextContent('load exploded');

    fireEvent.click(screen.getByRole('button', { name: /retry/i }));

    await waitFor(() => {
      expect(listFilesMock).toHaveBeenCalledTimes(2);
    });
  });

  it('refreshes the active folder when a blackboard file event arrives', async () => {
    render(<SharedFileBrowser tenantId="t-1" projectId="p-1" workspaceId="ws-1" />);

    await waitFor(() => {
      expect(listFilesMock).toHaveBeenCalledWith('t-1', 'p-1', 'ws-1', '/');
    });

    act(() => {
      useWorkspaceStore.getState().handleBlackboardEvent({
        type: 'blackboard_file_created',
        data: {
          workspace_id: 'ws-1',
          file: {
            id: 'file-2',
            workspace_id: 'ws-1',
            parent_path: '/',
            name: 'new.txt',
          },
        },
      });
    });

    await waitFor(() => {
      expect(listFilesMock).toHaveBeenCalledTimes(2);
    });
  });
});
