import { beforeEach, describe, expect, it, vi } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { geneMarketService } from '../../services/geneMarketService';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    delete: vi.fn(),
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

describe('geneMarketService', () => {
  const mockHttpClient = httpClient as unknown as {
    get: ReturnType<typeof vi.fn>;
    post: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('rates genes with the backend rating field', async () => {
    mockHttpClient.post.mockResolvedValue({ id: 'rating-1' });

    await geneMarketService.rateGene('gene-1', { rating: 5, comment: 'Good' });

    expect(mockHttpClient.post).toHaveBeenCalledWith('/genes/gene-1/ratings', {
      rating: 5,
      comment: 'Good',
    });
  });

  it('lists gene evolution events with a gene_id query parameter', async () => {
    mockHttpClient.get.mockResolvedValue({ events: [], total: 0, page: 1, page_size: 20 });

    await geneMarketService.listGeneEvolutionEvents('gene-1', { page: 2, page_size: 10 });

    expect(mockHttpClient.get).toHaveBeenCalledWith('/genes/evolution', {
      params: { gene_id: 'gene-1', page: 2, page_size: 10 },
    });
  });
});
