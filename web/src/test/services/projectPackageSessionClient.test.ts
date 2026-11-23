import { afterEach, describe, expect, it, vi } from 'vitest';

import { projectSessionClient } from '@/projectPackages/sessionClient';
import { kernelHttpClient } from '@/services/client/kernelHttpClient';

vi.mock('@/services/client/kernelHttpClient', () => ({
  kernelHttpClient: { get: vi.fn(), post: vi.fn() },
}));

function switchIdentity(token: string) {
  localStorage.setItem('memstack-auth-storage', JSON.stringify({ state: { token } }));
}

afterEach(() => {
  vi.clearAllMocks();
  localStorage.removeItem('memstack-auth-storage');
});

describe('signed package transport', () => {
  it('rejects an old mutation before transport when another tab switches identity', async () => {
    switchIdentity('previous');
    const client = projectSessionClient('previous', new AbortController().signal);
    switchIdentity('next');
    await expect(client.post('/install', {})).rejects.toMatchObject({ name: 'AbortError' });
    expect(kernelHttpClient.post).not.toHaveBeenCalled();
  });

  it('drops a response from an authorized request after logout', async () => {
    switchIdentity('previous');
    const controller = new AbortController();
    const client = projectSessionClient('previous', controller.signal);
    let deliver: (value: string) => void = () => {};
    vi.mocked(kernelHttpClient.get).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          deliver = resolve;
        })
    );
    const result = client.get('/project-packages/projects/');
    expect(kernelHttpClient.get).toHaveBeenCalledWith('/project-packages/projects/', {
      headers: { Authorization: 'Bearer previous' },
      signal: controller.signal,
    });
    localStorage.removeItem('memstack-auth-storage');
    deliver('old-projects');
    await expect(result).rejects.toMatchObject({ name: 'AbortError' });
  });
});
