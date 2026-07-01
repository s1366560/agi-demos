import { beforeEach, describe, expect, it, vi } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { graphStoreAPI, retrievalStoreAPI } from '../../services/api';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    delete: vi.fn(),
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

describe('backend store API', () => {
  const mockHttpClient = httpClient as unknown as {
    get: ReturnType<typeof vi.fn>;
    post: ReturnType<typeof vi.fn>;
    put: ReturnType<typeof vi.fn>;
    delete: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists graph stores with tenant scoping and unwraps the API envelope', async () => {
    const stores = [
      {
        id: '__env_neo4j__',
        tenant_id: 'tenant-1',
        name: 'neo4j (env)',
        engine_type: 'neo4j',
        status: 'connected',
        connection_config: { uri: 'env' },
        index_config: {},
        source: 'env',
        readonly: true,
      },
    ];
    mockHttpClient.get.mockResolvedValue({ success: true, data: stores });

    const result = await graphStoreAPI.list('tenant-1');

    expect(mockHttpClient.get).toHaveBeenCalledWith('/graph-stores', {
      params: { tenant_id: 'tenant-1' },
    });
    expect(result).toEqual(stores);
  });

  it('creates retrieval stores with tenant query params', async () => {
    const store = {
      id: 'store-1',
      tenant_id: 'tenant-1',
      name: 'weknora',
      engine_type: 'weknora_remote',
      status: 'disconnected',
      connection_config: { base_url: 'http://host:8080/api/v1', api_key: '***' },
      index_config: {},
      source: 'user',
      readonly: false,
    };
    mockHttpClient.post.mockResolvedValue({ success: true, data: store });

    const result = await retrievalStoreAPI.create('tenant-1', {
      name: 'weknora',
      engine_type: 'weknora_remote',
      connection_config: {
        base_url: 'http://host:8080/api/v1',
        api_key: 'secret',
        knowledge_base_id: 'kb-1',
      },
    });

    expect(mockHttpClient.post).toHaveBeenCalledWith(
      '/retrieval-stores',
      {
        name: 'weknora',
        engine_type: 'weknora_remote',
        connection_config: {
          base_url: 'http://host:8080/api/v1',
          api_key: 'secret',
          knowledge_base_id: 'kb-1',
        },
      },
      { params: { tenant_id: 'tenant-1' } }
    );
    expect(result.connection_config.api_key).toBe('***');
  });

  it('preserves success false test results for the UI', async () => {
    mockHttpClient.post.mockResolvedValue({
      success: false,
      error: 'connection refused',
    });

    const result = await graphStoreAPI.testRaw('tenant-1', {
      engine_type: 'neo4j',
      connection_config: { uri: 'bolt://localhost:7687' },
    });

    expect(result).toEqual({
      success: false,
      version: null,
      error: 'connection refused',
    });
  });

  it('throws when a CRUD envelope reports failure', async () => {
    mockHttpClient.get.mockResolvedValue({ success: false, error: 'not allowed' });

    await expect(retrievalStoreAPI.list('tenant-1')).rejects.toThrow('not allowed');
  });
});
