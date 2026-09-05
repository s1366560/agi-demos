import { beforeEach, describe, expect, it, vi } from 'vitest';

import { apiFetch } from '../../services/client/urlUtils';
import { subagentTemplateService } from '../../services/subagentTemplateService';

vi.mock('../../services/client/urlUtils', () => ({
  apiFetch: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

function jsonResponse(data: unknown): Response {
  return {
    json: vi.fn().mockResolvedValue(data),
  } as unknown as Response;
}

describe('subagentTemplateService', () => {
  const mockApiFetch = apiFetch as unknown as {
    get: ReturnType<typeof vi.fn>;
    post: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('maps marketplace list filters to backend query, limit, and offset parameters', async () => {
    mockApiFetch.get.mockImplementation(async (...args: any[]) =>
      args[1](jsonResponse({ templates: [], total: 0 }), {
        signal: args[2]?.signal ?? new AbortController().signal,
        check() {
          if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
        },
      })
    );

    const result = await subagentTemplateService.list({
      category: 'coding',
      search: 'review',
      page: 3,
      page_size: 25,
    });

    expect(mockApiFetch.get).toHaveBeenCalledWith(
      '/subagents/templates/list?category=coding&query=review&limit=25&offset=50',
      expect.any(Function)
    );
    expect(result).toEqual({ templates: [], total: 0, page: 3, page_size: 25 });
  });

  it('installs templates without sending an unsupported request body', async () => {
    mockApiFetch.post.mockImplementation(async (...args: any[]) =>
      args[2](jsonResponse({ id: 'subagent-1', name: 'reviewer', display_name: 'Reviewer' }), {
        signal: args[3]?.signal ?? new AbortController().signal,
        check() {
          if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
        },
      })
    );

    const result = await subagentTemplateService.install('template-1');

    expect(mockApiFetch.post).toHaveBeenCalledWith(
      '/subagents/templates/template-1/install',
      undefined,
      expect.any(Function)
    );
    expect(result).toMatchObject({ id: 'subagent-1', name: 'reviewer' });
  });

  it('maps the backend created count to the marketplace seeded contract', async () => {
    mockApiFetch.post.mockImplementation(async (...args: any[]) =>
      args[2](jsonResponse({ created: 3, message: 'Seeded 3 builtin templates' }), {
        signal: args[3]?.signal ?? new AbortController().signal,
        check() {
          if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
        },
      })
    );

    const result = await subagentTemplateService.seed();

    expect(mockApiFetch.post).toHaveBeenCalledWith(
      '/subagents/templates/seed',
      undefined,
      expect.any(Function)
    );
    expect(result).toEqual({ seeded: 3 });
  });

  it('fails closed when the backend omits a valid created count', async () => {
    mockApiFetch.post.mockImplementation(async (...args: any[]) =>
      args[2](jsonResponse({ message: 'seeded' }), {
        signal: args[3]?.signal ?? new AbortController().signal,
        check() {
          if (this.signal.aborted) throw new DOMException('cancelled', 'AbortError');
        },
      })
    );

    await expect(subagentTemplateService.seed()).rejects.toThrow(
      'subagent_template_seed_contract_invalid'
    );
  });
});
