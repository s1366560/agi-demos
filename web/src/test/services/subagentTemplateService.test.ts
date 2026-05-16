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
    mockApiFetch.get.mockResolvedValue(jsonResponse({ templates: [], total: 0 }));

    const result = await subagentTemplateService.list({
      category: 'coding',
      search: 'review',
      page: 3,
      page_size: 25,
    });

    expect(mockApiFetch.get).toHaveBeenCalledWith(
      '/subagents/templates/list?category=coding&query=review&limit=25&offset=50'
    );
    expect(result).toEqual({ templates: [], total: 0, page: 3, page_size: 25 });
  });

  it('installs templates without sending an unsupported request body', async () => {
    mockApiFetch.post.mockResolvedValue(
      jsonResponse({ id: 'subagent-1', name: 'reviewer', display_name: 'Reviewer' })
    );

    const result = await subagentTemplateService.install('template-1');

    expect(mockApiFetch.post).toHaveBeenCalledWith('/subagents/templates/template-1/install');
    expect(result).toMatchObject({ id: 'subagent-1', name: 'reviewer' });
  });
});
