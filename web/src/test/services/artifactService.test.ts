import { beforeEach, describe, expect, it, vi } from 'vitest';

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
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('uses apiFetch for local artifact API URLs', async () => {
    const response = new Response('artifact');
    vi.mocked(apiFetch.get).mockResolvedValueOnce(response);

    const result = await fetchArtifactResource('/api/v1/artifacts/artifact-1/download');

    expect(result).toBe(response);
    expect(apiFetch.get).toHaveBeenCalledWith('/api/v1/artifacts/artifact-1/download', undefined);
  });

  it('keeps presigned external URLs on plain fetch', async () => {
    const response = new Response('artifact');
    const fetchMock = vi.fn().mockResolvedValueOnce(response);
    vi.stubGlobal('fetch', fetchMock);

    const result = await fetchArtifactResource('https://storage.example.com/object?signature=abc');

    expect(result).toBe(response);
    expect(fetchMock).toHaveBeenCalledWith(
      'https://storage.example.com/object?signature=abc',
      undefined
    );
    expect(apiFetch.get).not.toHaveBeenCalled();
  });
});
