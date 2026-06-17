import { beforeEach, describe, expect, it, vi } from 'vitest';

import { geneMarketService } from '@/services/geneMarketService';
import { useGeneMarketStore } from '@/stores/geneMarket';

import type { GeneResponse, GenomeResponse } from '@/services/geneMarketService';

vi.mock('@/services/geneMarketService', () => ({
  geneMarketService: {
    createGeneReview: vi.fn(),
    deleteGeneReview: vi.fn(),
    getGeneReviews: vi.fn(),
    listGenes: vi.fn(),
    publishGene: vi.fn(),
    publishGenome: vi.fn(),
    unpublishGene: vi.fn(),
    unpublishGenome: vi.fn(),
  },
}));

const gene = (overrides: Partial<GeneResponse> = {}): GeneResponse => ({
  avg_rating: null,
  category: 'tool',
  created_at: '2026-06-17T00:00:00Z',
  created_by: 'user-1',
  created_by_instance_id: null,
  dependencies: [],
  description: null,
  effectiveness_score: null,
  icon: null,
  id: 'gene-1',
  install_count: 0,
  is_featured: false,
  is_published: false,
  manifest: {},
  name: 'Code Review',
  parent_gene_id: null,
  review_status: null,
  short_description: null,
  slug: 'code-review',
  source: 'manual',
  source_ref: null,
  synergies: [],
  tags: [],
  tenant_id: 'tenant-2',
  updated_at: null,
  version: '1.0.0',
  visibility: 'public',
  ...overrides,
});

const genome = (overrides: Partial<GenomeResponse> = {}): GenomeResponse => ({
  avg_rating: null,
  config_override: {},
  created_at: '2026-06-17T00:00:00Z',
  created_by: 'user-1',
  description: null,
  gene_slugs: ['code-review'],
  icon: null,
  id: 'genome-1',
  install_count: 0,
  is_featured: false,
  is_published: false,
  name: 'Review Pack',
  short_description: null,
  slug: 'review-pack',
  tenant_id: 'tenant-2',
  updated_at: null,
  visibility: 'public',
  ...overrides,
});

describe('gene market store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useGeneMarketStore.getState().reset();
    vi.mocked(geneMarketService.getGeneReviews).mockResolvedValue({ items: [], total: 0 });
  });

  it('initializes review state after reset', () => {
    const state = useGeneMarketStore.getState();

    expect(state.reviews).toEqual([]);
    expect(state.reviewsTotal).toBe(0);
    expect(state.reviewsLoading).toBe(false);
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

  it('updates gene list and current gene after publishing', async () => {
    const draftGene = gene({ is_published: false });
    const publishedGene = gene({ is_published: true });
    useGeneMarketStore.setState({
      genes: [draftGene],
      currentGene: draftGene,
    });
    vi.mocked(geneMarketService.publishGene).mockResolvedValue(publishedGene);

    const result = await useGeneMarketStore
      .getState()
      .publishGene('gene-1', { tenant_id: 'tenant-2' });

    expect(result.is_published).toBe(true);
    expect(geneMarketService.publishGene).toHaveBeenCalledWith('gene-1', {
      tenant_id: 'tenant-2',
    });
    expect(useGeneMarketStore.getState().genes[0]?.is_published).toBe(true);
    expect(useGeneMarketStore.getState().currentGene?.is_published).toBe(true);
    expect(useGeneMarketStore.getState().isSubmitting).toBe(false);
  });

  it('updates genome list and current genome after unpublishing', async () => {
    const publishedGenome = genome({ is_published: true });
    const draftGenome = genome({ is_published: false });
    useGeneMarketStore.setState({
      genomes: [publishedGenome],
      currentGenome: publishedGenome,
    });
    vi.mocked(geneMarketService.unpublishGenome).mockResolvedValue(draftGenome);

    const result = await useGeneMarketStore
      .getState()
      .unpublishGenome('genome-1', { tenant_id: 'tenant-2' });

    expect(result.is_published).toBe(false);
    expect(geneMarketService.unpublishGenome).toHaveBeenCalledWith('genome-1', {
      tenant_id: 'tenant-2',
    });
    expect(useGeneMarketStore.getState().genomes[0]?.is_published).toBe(false);
    expect(useGeneMarketStore.getState().currentGenome?.is_published).toBe(false);
    expect(useGeneMarketStore.getState().isSubmitting).toBe(false);
  });

  it('fetches detail-scoped genome genes without replacing marketplace list state', async () => {
    const marketplaceGene = gene({ id: 'market-gene', slug: 'market-gene' });
    const slugWindow = [
      'gene-2',
      'gene-0',
      ...Array.from({ length: 98 }, (_, index) => `missing-${String(index)}`),
      'gene-100',
    ];
    useGeneMarketStore.setState({
      genes: [marketplaceGene],
      geneTotal: 42,
    });
    vi.mocked(geneMarketService.listGenes).mockImplementation(async (params) => {
      if (params?.slugs?.includes('gene-100')) {
        return { genes: [gene({ id: 'gene-100', slug: 'gene-100' })], total: 1 };
      }
      return {
        genes: [gene({ id: 'gene-0', slug: 'gene-0' }), gene({ id: 'gene-2', slug: 'gene-2' })],
        total: 2,
      };
    });

    const result = await useGeneMarketStore
      .getState()
      .fetchGenomeGenes(slugWindow, { tenant_id: 'tenant-2' });

    expect(geneMarketService.listGenes).toHaveBeenNthCalledWith(1, {
      tenant_id: 'tenant-2',
      slugs: slugWindow.slice(0, 100),
      page_size: 100,
    });
    expect(geneMarketService.listGenes).toHaveBeenNthCalledWith(2, {
      tenant_id: 'tenant-2',
      slugs: ['gene-100'],
      page_size: 1,
    });
    expect(result.map((item) => item.slug)).toEqual(['gene-2', 'gene-0', 'gene-100']);
    expect(useGeneMarketStore.getState().currentGenomeGenes.map((item) => item.slug)).toEqual([
      'gene-2',
      'gene-0',
      'gene-100',
    ]);
    expect(useGeneMarketStore.getState().genes).toEqual([marketplaceGene]);
    expect(useGeneMarketStore.getState().geneTotal).toBe(42);
    expect(useGeneMarketStore.getState().currentGenomeGenesLoading).toBe(false);
  });
});
