import { beforeEach, describe, expect, it, vi } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { instanceTemplateService } from '../../services/instanceTemplateService';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    delete: vi.fn(),
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

describe('instanceTemplateService', () => {
  const mockHttpClient = httpClient as unknown as {
    get: ReturnType<typeof vi.fn>;
    post: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('creates templates with backend schema fields', async () => {
    mockHttpClient.post.mockResolvedValue({ id: 'tmpl-1' });

    await instanceTemplateService.create({
      name: 'Starter',
      slug: 'starter',
      default_config: { replicas: 1 },
      description: 'Base template',
    });

    expect(mockHttpClient.post).toHaveBeenCalledWith('/instance-templates/', {
      name: 'Starter',
      slug: 'starter',
      default_config: { replicas: 1 },
      description: 'Base template',
    });
  });

  it('sends clone name required by the backend', async () => {
    mockHttpClient.post.mockResolvedValue({ id: 'tmpl-copy' });

    await instanceTemplateService.clone('tmpl-1', 'Copy of Starter');

    expect(mockHttpClient.post).toHaveBeenCalledWith('/instance-templates/tmpl-1/clone', {
      new_name: 'Copy of Starter',
    });
  });

  it('fills item defaults for the template item endpoint', async () => {
    mockHttpClient.post.mockResolvedValue({ id: 'item-1' });

    await instanceTemplateService.addItem('tmpl-1', { item_slug: 'summarizer' });

    expect(mockHttpClient.post).toHaveBeenCalledWith('/instance-templates/tmpl-1/items', {
      template_id: 'tmpl-1',
      item_slug: 'summarizer',
      item_type: 'gene',
      display_order: 0,
    });
  });
});
