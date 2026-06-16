import { beforeEach, describe, expect, it, vi } from 'vitest';

import { geneMarketService } from '@/services/geneMarketService';
import { useGeneMarketStore } from '@/stores/geneMarket';

vi.mock('@/services/geneMarketService', () => ({
  geneMarketService: {
    createGeneReview: vi.fn(),
    deleteGeneReview: vi.fn(),
    getGeneReviews: vi.fn(),
  },
}));

describe('gene market store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useGeneMarketStore.getState().reset();
    vi.mocked(geneMarketService.getGeneReviews).mockResolvedValue({ items: [], total: 0 });
  });

  it('refreshes selected-tenant reviews after creating a gene review', async () => {
    vi.mocked(geneMarketService.createGeneReview).mockResolvedValue({ id: 'review-1' } as any);

    await useGeneMarketStore
      .getState()
      .createGeneReview('gene-1', { rating: 5, content: 'Helpful' }, { tenant_id: 'tenant-2' });

    expect(geneMarketService.createGeneReview).toHaveBeenCalledWith(
      'gene-1',
      { rating: 5, content: 'Helpful' },
      { tenant_id: 'tenant-2' }
    );
    expect(geneMarketService.getGeneReviews).toHaveBeenCalledWith('gene-1', 1, 10, {
      tenant_id: 'tenant-2',
    });
  });

  it('refreshes selected-tenant reviews after deleting a gene review', async () => {
    vi.mocked(geneMarketService.deleteGeneReview).mockResolvedValue(undefined);

    await useGeneMarketStore
      .getState()
      .deleteGeneReview('gene-1', 'review-1', { tenant_id: 'tenant-2' });

    expect(geneMarketService.deleteGeneReview).toHaveBeenCalledWith('gene-1', 'review-1', {
      tenant_id: 'tenant-2',
    });
    expect(geneMarketService.getGeneReviews).toHaveBeenCalledWith('gene-1', 1, 10, {
      tenant_id: 'tenant-2',
    });
  });
});
