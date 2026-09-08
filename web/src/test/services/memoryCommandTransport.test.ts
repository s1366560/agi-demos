import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { memoryCommandTransport } from '../../services/memoryCommandTransport';
import { httpClient } from '../../services/client/httpClient';
import { ApiError, ApiErrorType } from '../../services/client/ApiError';
import { installHttpAdmissionFixtureV2 } from './webHttpAdmissionFixtureV2';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const challenge = () =>
  new ApiError(ApiErrorType.UNKNOWN, 'UNKNOWN_ERROR', 'Required', 428, {
    detail: { code: 'memory_command_precondition_required' },
  });
const network = () => new ApiError(ApiErrorType.NETWORK, 'NETWORK_ERROR', 'Lost response');
const conflict = () => new ApiError(ApiErrorType.CONFLICT, 'revision_conflict', 'Conflict', 409);
const idempotencyKey = '11111111-1111-4111-8111-111111111111';

describe('memory command transport', () => {
  let cleanup: () => Promise<void>;
  beforeEach(() => {
    vi.resetAllMocks();
    cleanup = installHttpAdmissionFixtureV2();
  });
  afterEach(async () => {
    await cleanup();
  });

  it('preserves legacy create without sending unsupported command headers', async () => {
    vi.mocked(httpClient.post).mockResolvedValue({ id: 'm1' });
    await memoryCommandTransport.create('p1', { title: 'Title', content: 'Body' });
    expect(httpClient.post).toHaveBeenCalledTimes(1);
    expect(httpClient.post).toHaveBeenCalledWith(
      '/memories/',
      {
        title: 'Title',
        content: 'Body',
        project_id: 'p1',
      },
      { operation: expect.any(Object) }
    );
  });

  it('negotiates the exact create challenge and retries with one immutable command', async () => {
    const draft = { title: 'Title', content: 'Original' };
    vi.mocked(httpClient.post)
      .mockImplementationOnce(async () => {
        draft.content = 'Changed while awaiting';
        throw challenge();
      })
      .mockRejectedValueOnce(network())
      .mockResolvedValueOnce({ id: 'm1' });
    await memoryCommandTransport.create('p1', draft);
    expect(httpClient.post).toHaveBeenCalledTimes(3);
    const [, body, first] = vi.mocked(httpClient.post).mock.calls[1]!;
    const [, retryBody, retry] = vi.mocked(httpClient.post).mock.calls[2]!;
    expect(body).toEqual({ title: 'Title', content: 'Original', project_id: 'p1' });
    expect(retryBody).toEqual(body);
    expect(first?.headers).toEqual({
      'Idempotency-Key': expect.any(String),
      'X-Memory-Expected-Revision': '0',
    });
    expect(retry?.headers).toEqual(first?.headers);
    expect(retry?.operation).toBe(first?.operation);
  });

  it('uses the displayed update version and retains a concurrent revision conflict', async () => {
    const error = conflict();
    vi.mocked(httpClient.patch).mockRejectedValueOnce(challenge()).mockRejectedValueOnce(error);
    await expect(
      memoryCommandTransport.update('p1', 'm1', { content: 'Edit', version: 3 })
    ).rejects.toBe(error);
    expect(httpClient.patch).toHaveBeenCalledTimes(2);
    expect(httpClient.patch).toHaveBeenLastCalledWith(
      '/memories/m1',
      { content: 'Edit', version: 3 },
      {
        operation: expect.any(Object),
        params: { project_id: 'p1' },
        headers: { 'Idempotency-Key': expect.any(String), 'X-Memory-Expected-Revision': '3' },
      }
    );
    expect(httpClient.get).not.toHaveBeenCalled();
  });

  it('deletes only the displayed revision without fetching a newer version', async () => {
    const error = conflict();
    vi.mocked(httpClient.delete).mockRejectedValueOnce(challenge()).mockRejectedValueOnce(error);
    await expect(memoryCommandTransport.delete('p1', 'm1', 7)).rejects.toBe(error);
    expect(httpClient.get).not.toHaveBeenCalled();
    expect(httpClient.delete).toHaveBeenCalledTimes(2);
    expect(httpClient.delete).toHaveBeenLastCalledWith('/memories/m1', {
      operation: expect.any(Object),
      params: { project_id: 'p1' },
      headers: { 'Idempotency-Key': expect.any(String), 'X-Memory-Expected-Revision': '7' },
    });
  });

  it('captures a missing delete revision before any delete and never refreshes it after conflict', async () => {
    vi.mocked(httpClient.get).mockResolvedValue({ id: 'm1', project_id: 'p1', version: 4 });
    const error = conflict();
    vi.mocked(httpClient.delete).mockRejectedValueOnce(challenge()).mockRejectedValueOnce(error);
    await expect(memoryCommandTransport.delete('p1', 'm1')).rejects.toBe(error);
    expect(httpClient.get).toHaveBeenCalledTimes(1);
    expect(vi.mocked(httpClient.get).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(httpClient.delete).mock.invocationCallOrder[0]!
    );
    expect(vi.mocked(httpClient.delete).mock.calls[1]![1]?.headers).toMatchObject({
      'X-Memory-Expected-Revision': '4',
    });
  });

  it('can replay an explicitly retained command key without another legacy mutation', async () => {
    vi.mocked(httpClient.post).mockResolvedValue({ id: 'm1' });
    await memoryCommandTransport.create(
      'p1',
      { title: 'Title', content: 'Body' },
      { idempotencyKey }
    );
    expect(httpClient.post).toHaveBeenCalledTimes(1);
    expect(vi.mocked(httpClient.post).mock.calls[0]![2]?.headers).toEqual({
      'Idempotency-Key': idempotencyKey,
      'X-Memory-Expected-Revision': '0',
    });
  });

  it.each([
    new ApiError(ApiErrorType.UNKNOWN, 'UNKNOWN_ERROR', 'Other 428', 428, {
      detail: { code: 'other' },
    }),
    new ApiError(ApiErrorType.UNKNOWN, 'memory_command_precondition_required', 'Unstructured', 428),
    new ApiError(ApiErrorType.NOT_FOUND, 'NOT_FOUND', 'Missing project', 404),
    new ApiError(ApiErrorType.AUTHORIZATION, 'FORBIDDEN', 'Denied', 403),
    new ApiError(ApiErrorType.SERVER, 'UNAVAILABLE', 'Unavailable', 503),
    network(),
  ])('does not retry or downgrade an unrecognized initial response: %s', async (error) => {
    vi.mocked(httpClient.post).mockRejectedValue(error);
    await expect(
      memoryCommandTransport.create('p1', { title: 'Title', content: 'Body' })
    ).rejects.toBe(error);
    expect(httpClient.post).toHaveBeenCalledTimes(1);
  });

  it('bounds uncertain versioned retries while preserving the command key', async () => {
    const error = network();
    vi.mocked(httpClient.post).mockRejectedValueOnce(challenge()).mockRejectedValue(error);
    await expect(
      memoryCommandTransport.create('p1', { title: 'Title', content: 'Body' })
    ).rejects.toBe(error);
    expect(httpClient.post).toHaveBeenCalledTimes(3);
    expect(vi.mocked(httpClient.post).mock.calls[2]![2]?.headers).toEqual(
      vi.mocked(httpClient.post).mock.calls[1]![2]?.headers
    );
  });

  it('rejects malformed revisions before mutation', async () => {
    for (const version of [0, -1, 1.5, 2147483647, NaN]) {
      await expect(memoryCommandTransport.update('p1', 'm1', { version })).rejects.toThrow();
      await expect(memoryCommandTransport.delete('p1', 'm1', version)).rejects.toThrow();
    }
    expect(httpClient.patch).not.toHaveBeenCalled();
    expect(httpClient.delete).not.toHaveBeenCalled();
  });

  it('cancels the command when identity admission changes after the challenge', async () => {
    let closing: Promise<void> | undefined;
    vi.mocked(httpClient.post).mockImplementationOnce(async () => {
      closing = cleanup();
      throw challenge();
    });
    await expect(
      memoryCommandTransport.create('p1', { title: 'Title', content: 'Body' })
    ).rejects.toThrow();
    await closing;
    expect(httpClient.post).toHaveBeenCalledTimes(1);
  });

  it('rejects a cross-project delete lookup before mutation', async () => {
    vi.mocked(httpClient.get).mockResolvedValue({ id: 'm1', project_id: 'other', version: 4 });
    await expect(memoryCommandTransport.delete('p1', 'm1')).rejects.toThrow();
    expect(httpClient.delete).not.toHaveBeenCalled();
  });
});
