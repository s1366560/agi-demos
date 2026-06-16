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

  it('lists genes with marketplace filters and pagination', async () => {
    mockHttpClient.get.mockResolvedValue({ genes: [], total: 0, page: 1, page_size: 20 });

    await geneMarketService.listGenes({
      page: 2,
      page_size: 50,
      search: 'review',
      category: 'tool',
      visibility: 'org_private',
    });

    expect(mockHttpClient.get).toHaveBeenCalledWith('/genes/', {
      params: {
        page: 2,
        page_size: 50,
        search: 'review',
        category: 'tool',
        visibility: 'org_private',
      },
    });
  });

  it('rates genes with the backend rating field', async () => {
    mockHttpClient.post.mockResolvedValue({ id: 'rating-1' });

    await geneMarketService.rateGene('gene-1', { rating: 5, comment: 'Good' });

    expect(mockHttpClient.post).toHaveBeenCalledWith('/genes/gene-1/ratings', {
      rating: 5,
      comment: 'Good',
    });
  });

  it('scopes gene mutations with selected tenant query params', async () => {
    mockHttpClient.post.mockResolvedValue({ id: 'rating-1' });

    await geneMarketService.rateGene(
      'gene-1',
      { rating: 5, comment: 'Good' },
      { tenant_id: 'tenant-2' }
    );

    expect(mockHttpClient.post).toHaveBeenCalledWith(
      '/genes/gene-1/ratings',
      {
        rating: 5,
        comment: 'Good',
      },
      { params: { tenant_id: 'tenant-2' } }
    );
  });

  it('lists gene evolution events with a gene_id query parameter', async () => {
    mockHttpClient.get.mockResolvedValue({ events: [], total: 0, page: 1, page_size: 20 });

    await geneMarketService.listGeneEvolutionEvents('gene-1', { page: 2, page_size: 10 });

    expect(mockHttpClient.get).toHaveBeenCalledWith('/genes/evolution', {
      params: { gene_id: 'gene-1', page: 2, page_size: 10 },
    });
  });

  it('creates genes with the backend slug-based contract', async () => {
    mockHttpClient.post.mockResolvedValue({ id: 'gene-1' });

    await geneMarketService.createGene({
      name: 'Code Review',
      slug: 'code-review',
      short_description: 'Review code changes',
      manifest: { tools: ['lint'] },
      dependencies: ['quality-base'],
      synergies: ['test-writer'],
    });

    expect(mockHttpClient.post).toHaveBeenCalledWith('/genes/', {
      name: 'Code Review',
      slug: 'code-review',
      short_description: 'Review code changes',
      manifest: { tools: ['lint'] },
      dependencies: ['quality-base'],
      synergies: ['test-writer'],
    });
  });

  it('creates genomes with gene slugs and config overrides', async () => {
    mockHttpClient.post.mockResolvedValue({ id: 'genome-1' });

    await geneMarketService.createGenome({
      name: 'Review Pack',
      slug: 'review-pack',
      gene_slugs: ['code-review', 'test-writer'],
      config_override: { 'code-review': { strict: true } },
    });

    expect(mockHttpClient.post).toHaveBeenCalledWith('/genes/genomes', {
      name: 'Review Pack',
      slug: 'review-pack',
      gene_slugs: ['code-review', 'test-writer'],
      config_override: { 'code-review': { strict: true } },
    });
  });

  it('lists instance evolution events with backend event_type filters', async () => {
    mockHttpClient.get.mockResolvedValue({ events: [], total: 0, page: 1, page_size: 20 });

    await geneMarketService.listEvolutionEvents('instance-1', {
      page: 1,
      page_size: 20,
      event_type: 'learned',
    });

    expect(mockHttpClient.get).toHaveBeenCalledWith('/genes/evolution', {
      params: {
        instance_id: 'instance-1',
        page: 1,
        page_size: 20,
        event_type: 'learned',
      },
    });
  });
});
