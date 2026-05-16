import { beforeEach, describe, expect, it, vi } from 'vitest';

import { instanceFileService } from '@/services/instanceFileService';

const { httpGetMock, httpDeleteMock } = vi.hoisted(() => ({
  httpGetMock: vi.fn(),
  httpDeleteMock: vi.fn(),
}));

vi.mock('@/services/client/httpClient', () => ({
  httpClient: {
    get: (...args: unknown[]) => httpGetMock(...args),
    delete: (...args: unknown[]) => httpDeleteMock(...args),
  },
}));

describe('instanceFileService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('encodes special characters in file paths while preserving directories', async () => {
    httpGetMock.mockResolvedValueOnce({ content: 'hello' });
    httpGetMock.mockResolvedValueOnce(new Blob(['hello']));
    httpDeleteMock.mockResolvedValueOnce({ deleted: true });

    const filePath = 'docs/notes #1?.md';

    await instanceFileService.previewFile('instance-1', filePath);
    await instanceFileService.downloadFile('instance-1', filePath);
    await instanceFileService.deleteFile('instance-1', filePath);

    expect(httpGetMock).toHaveBeenNthCalledWith(
      1,
      '/instances/instance-1/files/docs/notes%20%231%3F.md/content'
    );
    expect(httpGetMock).toHaveBeenNthCalledWith(
      2,
      '/instances/instance-1/files/docs/notes%20%231%3F.md/download',
      { responseType: 'blob' }
    );
    expect(httpDeleteMock).toHaveBeenCalledWith(
      '/instances/instance-1/files/docs/notes%20%231%3F.md'
    );
  });
});
