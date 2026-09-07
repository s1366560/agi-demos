import { beforeEach, describe, expect, it, vi } from 'vitest';

import { invitationService } from '@/services/invitationService';

const mocks = vi.hoisted(() => ({
  publicGet: vi.fn(),
  generationGet: vi.fn(),
  generationPost: vi.fn(),
}));
vi.mock('@/services/client/kernelHttpClient', () => ({
  kernelHttpClient: { get: mocks.publicGet },
}));
vi.mock('@/services/client/httpClient', () => ({
  httpClient: { get: mocks.generationGet, post: mocks.generationPost },
}));

describe('invitation identity transport boundaries', () => {
  beforeEach(() => vi.clearAllMocks());

  it('verifies public tokens before an authenticated generation exists', async () => {
    mocks.publicGet.mockResolvedValue({ valid: false });
    await expect(invitationService.verify('invalid-token')).resolves.toEqual({ valid: false });
    expect(mocks.publicGet).toHaveBeenCalledWith('/invitations/verify/invalid-token');
    expect(mocks.generationGet).not.toHaveBeenCalled();
  });

  it('keeps invitation acceptance inside the authenticated generation', async () => {
    mocks.generationPost.mockResolvedValue({ id: 'invitation-1' });
    await invitationService.accept('valid-token');
    expect(mocks.generationPost).toHaveBeenCalledWith('/invitations/accept/valid-token', {});
    expect(mocks.publicGet).not.toHaveBeenCalled();
  });
});
