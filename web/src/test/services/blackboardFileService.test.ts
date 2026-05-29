import { beforeEach, describe, expect, it, vi } from 'vitest';

import { blackboardFileService } from '@/services/blackboardFileService';

const { httpGetMock, httpPostMock, httpPatchMock, httpDeleteMock } = vi.hoisted(() => ({
  httpGetMock: vi.fn(),
  httpPostMock: vi.fn(),
  httpPatchMock: vi.fn(),
  httpDeleteMock: vi.fn(),
}));

vi.mock('@/services/client/httpClient', () => ({
  httpClient: {
    get: (...args: unknown[]) => httpGetMock(...args),
    post: (...args: unknown[]) => httpPostMock(...args),
    patch: (...args: unknown[]) => httpPatchMock(...args),
    delete: (...args: unknown[]) => httpDeleteMock(...args),
  },
}));

describe('blackboardFileService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists files with tenant/project/workspace scope and parent path', async () => {
    httpGetMock.mockResolvedValueOnce({ items: [{ id: 'file-1' }] });

    const result = await blackboardFileService.listFiles('tenant 1', 'project/1', 'ws-1', '/docs/');

    expect(httpGetMock).toHaveBeenCalledWith(
      '/tenants/tenant%201/projects/project%2F1/workspaces/ws-1/blackboard/files',
      { params: { parent_path: '/docs/' } }
    );
    expect(result).toEqual([{ id: 'file-1' }]);
  });

  it('creates directories through the mkdir endpoint', async () => {
    httpPostMock.mockResolvedValueOnce({ id: 'dir-1' });

    const result = await blackboardFileService.createDirectory(
      'tenant-1',
      'project-1',
      'ws-1',
      '/',
      'docs'
    );

    expect(httpPostMock).toHaveBeenCalledWith(
      '/tenants/tenant-1/projects/project-1/workspaces/ws-1/blackboard/files/mkdir',
      { parent_path: '/', name: 'docs' }
    );
    expect(result).toEqual({ id: 'dir-1' });
  });

  it('uploads multipart file data with the active parent path', async () => {
    httpPostMock.mockResolvedValueOnce({ id: 'file-1' });
    const file = new File(['hello'], 'hello.txt', { type: 'text/plain' });

    await blackboardFileService.uploadFile('tenant-1', 'project-1', 'ws-1', '/docs/', file);

    const [url, formData, config] = httpPostMock.mock.calls[0];
    expect(url).toBe(
      '/tenants/tenant-1/projects/project-1/workspaces/ws-1/blackboard/files/upload'
    );
    expect(formData.get('file')).toBe(file);
    expect(formData.get('parent_path')).toBe('/docs/');
    expect(config).toEqual({ headers: { 'Content-Type': 'multipart/form-data' } });
  });

  it('downloads and deletes files with encoded file ids', async () => {
    httpGetMock.mockResolvedValueOnce(new Blob(['hello']));
    httpDeleteMock.mockResolvedValueOnce({ deleted: true });

    await blackboardFileService.downloadFile('tenant-1', 'project-1', 'ws-1', 'file/1');
    const deleted = await blackboardFileService.deleteFile(
      'tenant-1',
      'project-1',
      'ws-1',
      'file/1'
    );

    expect(httpGetMock).toHaveBeenCalledWith(
      '/tenants/tenant-1/projects/project-1/workspaces/ws-1/blackboard/files/file%2F1/download',
      { responseType: 'blob' }
    );
    expect(httpDeleteMock).toHaveBeenCalledWith(
      '/tenants/tenant-1/projects/project-1/workspaces/ws-1/blackboard/files/file%2F1',
      { params: { recursive: false } }
    );
    expect(deleted).toBe(true);
  });

  it('passes recursive delete for directories', async () => {
    httpDeleteMock.mockResolvedValueOnce({ deleted: true });

    await blackboardFileService.deleteFile('tenant-1', 'project-1', 'ws-1', 'dir-1', true);

    expect(httpDeleteMock).toHaveBeenCalledWith(
      '/tenants/tenant-1/projects/project-1/workspaces/ws-1/blackboard/files/dir-1',
      { params: { recursive: true } }
    );
  });

  it('renames and moves files through the patch endpoint', async () => {
    httpPatchMock.mockResolvedValueOnce({ id: 'file-1', name: 'new.txt' });
    httpPatchMock.mockResolvedValueOnce({ id: 'file-1', parent_path: '/docs/' });

    await blackboardFileService.renameFile('tenant-1', 'project-1', 'ws-1', 'file/1', 'new.txt');
    await blackboardFileService.moveFile('tenant-1', 'project-1', 'ws-1', 'file/1', '/docs/');

    expect(httpPatchMock).toHaveBeenNthCalledWith(
      1,
      '/tenants/tenant-1/projects/project-1/workspaces/ws-1/blackboard/files/file%2F1',
      { name: 'new.txt' }
    );
    expect(httpPatchMock).toHaveBeenNthCalledWith(
      2,
      '/tenants/tenant-1/projects/project-1/workspaces/ws-1/blackboard/files/file%2F1',
      { parent_path: '/docs/' }
    );
  });

  it('copies files with destination path and optional new name', async () => {
    httpPostMock.mockResolvedValueOnce({ id: 'copy-1' });

    await blackboardFileService.copyFile(
      'tenant-1',
      'project-1',
      'ws-1',
      'file/1',
      '/docs/',
      'copy.txt'
    );

    expect(httpPostMock).toHaveBeenCalledWith(
      '/tenants/tenant-1/projects/project-1/workspaces/ws-1/blackboard/files/file%2F1/copy',
      { target_parent_path: '/docs/', name: 'copy.txt' }
    );
  });
});
