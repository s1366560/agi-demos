import { beforeEach, describe, expect, it, vi } from 'vitest';

import { geneMarketService } from '@/services/geneMarketService';
import { useGeneMarketStore } from '@/stores/geneMarket';

import type {
  GeneListResponse,
  GeneResponse,
  GenomeListResponse,
  GenomeResponse,
} from '@/services/geneMarketService';

vi.mock('@/services/geneMarketService', () => ({
  geneMarketService: {
    createGeneReview: vi.fn(),
    deleteGeneReview: vi.fn(),
    getGene: vi.fn(),
    getGeneReviews: vi.fn(),
    getGenome: vi.fn(),
    listGenes: vi.fn(),
    listGenomes: vi.fn(),
    publishGene: vi.fn(),
    publishGenome: vi.fn(),
    rateGene: vi.fn(),
    rateGenome: vi.fn(),
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

const geneListResponse = (genes: GeneResponse[]): GeneListResponse => ({
  genes,
  total: genes.length,
  page: 1,
  page_size: genes.length,
});

const genomeListResponse = (genomes: GenomeResponse[]): GenomeListResponse => ({
  genomes,
  total: genomes.length,
  page: 1,
  page_size: genomes.length,
});

const deferred = <T>() => {
  let resolve: (value: T | PromiseLike<T>) => void = () => {};
  let reject: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
};

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

  it('leaves review refresh pagination to the caller after creating a gene review', async () => {
    vi.mocked(geneMarketService.createGeneReview).mockResolvedValue({ id: 'review-1' } as any);

    await useGeneMarketStore
      .getState()
      .createGeneReview('gene-1', { rating: 5, content: 'Helpful' }, { tenant_id: 'tenant-2' });

    expect(geneMarketService.createGeneReview).toHaveBeenCalledWith(
      'gene-1',
      { rating: 5, content: 'Helpful' },
      { tenant_id: 'tenant-2' }
    );
    expect(geneMarketService.getGeneReviews).not.toHaveBeenCalled();
  });

  it('leaves review refresh pagination to the caller after deleting a gene review', async () => {
    vi.mocked(geneMarketService.deleteGeneReview).mockResolvedValue(undefined);

    await useGeneMarketStore
      .getState()
      .deleteGeneReview('gene-1', 'review-1', { tenant_id: 'tenant-2' });

    expect(geneMarketService.deleteGeneReview).toHaveBeenCalledWith('gene-1', 'review-1', {
      tenant_id: 'tenant-2',
    });
    expect(geneMarketService.getGeneReviews).not.toHaveBeenCalled();
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

  it('ignores stale gene detail responses after a newer detail request starts', async () => {
    const staleRequest = deferred<GeneResponse>();
    const latestRequest = deferred<GeneResponse>();
    vi.mocked(geneMarketService.getGene)
      .mockReturnValueOnce(staleRequest.promise)
      .mockReturnValueOnce(latestRequest.promise);

    const staleResult = useGeneMarketStore.getState().getGene('gene-1', { tenant_id: 'tenant-2' });
    const latestResult = useGeneMarketStore.getState().getGene('gene-2', { tenant_id: 'tenant-2' });

    latestRequest.resolve(gene({ id: 'gene-2', slug: 'test-writer', name: 'Test Writer' }));
    await expect(latestResult).resolves.toMatchObject({ id: 'gene-2' });
    expect(useGeneMarketStore.getState().currentGene?.id).toBe('gene-2');

    staleRequest.resolve(gene({ id: 'gene-1', slug: 'code-review', name: 'Code Review' }));
    await expect(staleResult).resolves.toMatchObject({ id: 'gene-1' });
    expect(useGeneMarketStore.getState().currentGene?.id).toBe('gene-2');
    expect(useGeneMarketStore.getState().isLoading).toBe(false);
  });

  it('ignores stale gene list responses after a newer list request starts', async () => {
    const staleRequest = deferred<GeneListResponse>();
    const latestRequest = deferred<GeneListResponse>();
    vi.mocked(geneMarketService.listGenes)
      .mockReturnValueOnce(staleRequest.promise)
      .mockReturnValueOnce(latestRequest.promise);

    const staleResult = useGeneMarketStore
      .getState()
      .listGenes({ tenant_id: 'tenant-1', search: 'old' });
    const latestResult = useGeneMarketStore
      .getState()
      .listGenes({ tenant_id: 'tenant-2', search: 'new' });

    latestRequest.resolve(
      geneListResponse([gene({ id: 'gene-2', tenant_id: 'tenant-2', slug: 'latest' })])
    );
    await expect(latestResult).resolves.toBeUndefined();
    expect(useGeneMarketStore.getState().genes.map((item) => item.id)).toEqual(['gene-2']);
    expect(useGeneMarketStore.getState().geneTotal).toBe(1);

    staleRequest.resolve(
      geneListResponse([gene({ id: 'gene-1', tenant_id: 'tenant-1', slug: 'stale' })])
    );
    await expect(staleResult).resolves.toBeUndefined();
    expect(useGeneMarketStore.getState().genes.map((item) => item.id)).toEqual(['gene-2']);
    expect(useGeneMarketStore.getState().isLoading).toBe(false);
  });

  it('ignores stale genome list responses after a newer list request starts', async () => {
    const staleRequest = deferred<GenomeListResponse>();
    const latestRequest = deferred<GenomeListResponse>();
    vi.mocked(geneMarketService.listGenomes)
      .mockReturnValueOnce(staleRequest.promise)
      .mockReturnValueOnce(latestRequest.promise);

    const staleResult = useGeneMarketStore
      .getState()
      .listGenomes({ tenant_id: 'tenant-1', is_published: false });
    const latestResult = useGeneMarketStore
      .getState()
      .listGenomes({ tenant_id: 'tenant-2', is_published: true });

    latestRequest.resolve(
      genomeListResponse([genome({ id: 'genome-2', tenant_id: 'tenant-2', slug: 'latest-pack' })])
    );
    await expect(latestResult).resolves.toBeUndefined();
    expect(useGeneMarketStore.getState().genomes.map((item) => item.id)).toEqual(['genome-2']);
    expect(useGeneMarketStore.getState().genomeTotal).toBe(1);

    staleRequest.resolve(
      genomeListResponse([genome({ id: 'genome-1', tenant_id: 'tenant-1', slug: 'stale-pack' })])
    );
    await expect(staleResult).resolves.toBeUndefined();
    expect(useGeneMarketStore.getState().genomes.map((item) => item.id)).toEqual(['genome-2']);
    expect(useGeneMarketStore.getState().isLoading).toBe(false);
  });

  it('invalidates pending gene detail responses when current gene is cleared', async () => {
    const pendingRequest = deferred<GeneResponse>();
    vi.mocked(geneMarketService.getGene).mockReturnValueOnce(pendingRequest.promise);

    const request = useGeneMarketStore.getState().getGene('gene-1', { tenant_id: 'tenant-2' });
    useGeneMarketStore.getState().setCurrentGene(null);

    pendingRequest.resolve(gene());
    await expect(request).resolves.toMatchObject({ id: 'gene-1' });
    expect(useGeneMarketStore.getState().currentGene).toBeNull();
    expect(useGeneMarketStore.getState().isLoading).toBe(false);
  });

  it('ignores stale genome detail and included-gene responses after newer requests start', async () => {
    const staleGenomeRequest = deferred<GenomeResponse>();
    const latestGenomeRequest = deferred<GenomeResponse>();
    const staleGenesRequest = deferred<GeneListResponse>();
    const latestGenesRequest = deferred<GeneListResponse>();
    vi.mocked(geneMarketService.getGenome)
      .mockReturnValueOnce(staleGenomeRequest.promise)
      .mockReturnValueOnce(latestGenomeRequest.promise);
    vi.mocked(geneMarketService.listGenes)
      .mockReturnValueOnce(staleGenesRequest.promise)
      .mockReturnValueOnce(latestGenesRequest.promise);

    const staleGenomeResult = useGeneMarketStore
      .getState()
      .getGenome('genome-1', { tenant_id: 'tenant-2' });
    const latestGenomeResult = useGeneMarketStore
      .getState()
      .getGenome('genome-2', { tenant_id: 'tenant-2' });
    const staleGenesResult = useGeneMarketStore
      .getState()
      .fetchGenomeGenes(['code-review'], { tenant_id: 'tenant-2' });
    const latestGenesResult = useGeneMarketStore
      .getState()
      .fetchGenomeGenes(['test-writer'], { tenant_id: 'tenant-2' });

    latestGenomeRequest.resolve(genome({ id: 'genome-2', slug: 'test-pack', name: 'Test Pack' }));
    latestGenesRequest.resolve(
      geneListResponse([gene({ id: 'gene-2', slug: 'test-writer', name: 'Test Writer' })])
    );

    await expect(latestGenomeResult).resolves.toMatchObject({ id: 'genome-2' });
    await expect(latestGenesResult).resolves.toHaveLength(1);
    expect(useGeneMarketStore.getState().currentGenome?.id).toBe('genome-2');
    expect(useGeneMarketStore.getState().currentGenomeGenes.map((item) => item.slug)).toEqual([
      'test-writer',
    ]);

    staleGenomeRequest.resolve(genome({ id: 'genome-1', slug: 'review-pack' }));
    staleGenesRequest.resolve(geneListResponse([gene({ slug: 'code-review' })]));

    await expect(staleGenomeResult).resolves.toMatchObject({ id: 'genome-1' });
    await expect(staleGenesResult).resolves.toHaveLength(1);
    expect(useGeneMarketStore.getState().currentGenome?.id).toBe('genome-2');
    expect(useGeneMarketStore.getState().currentGenomeGenes.map((item) => item.slug)).toEqual([
      'test-writer',
    ]);
    expect(useGeneMarketStore.getState().currentGenomeGenesLoading).toBe(false);
  });

  it('refreshes gene list and current gene after rating', async () => {
    const staleGene = gene({ avg_rating: 2 });
    const refreshedGene = gene({ avg_rating: 4.5 });
    useGeneMarketStore.setState({
      genes: [staleGene],
      currentGene: staleGene,
    });
    vi.mocked(geneMarketService.rateGene).mockResolvedValue({ id: 'rating-1' } as any);
    vi.mocked(geneMarketService.getGene).mockResolvedValue(refreshedGene);

    await useGeneMarketStore
      .getState()
      .rateGene('gene-1', { rating: 5, comment: 'Helpful' }, { tenant_id: 'tenant-2' });

    expect(geneMarketService.rateGene).toHaveBeenCalledWith(
      'gene-1',
      { rating: 5, comment: 'Helpful' },
      { tenant_id: 'tenant-2' }
    );
    expect(geneMarketService.getGene).toHaveBeenCalledWith('gene-1', {
      tenant_id: 'tenant-2',
    });
    expect(useGeneMarketStore.getState().genes[0]?.avg_rating).toBe(4.5);
    expect(useGeneMarketStore.getState().currentGene?.avg_rating).toBe(4.5);
    expect(useGeneMarketStore.getState().isSubmitting).toBe(false);
  });

  it('refreshes genome list and current genome after rating', async () => {
    const staleGenome = genome({ avg_rating: 1 });
    const refreshedGenome = genome({ avg_rating: 3.5 });
    useGeneMarketStore.setState({
      genomes: [staleGenome],
      currentGenome: staleGenome,
    });
    vi.mocked(geneMarketService.rateGenome).mockResolvedValue({ id: 'rating-1' } as any);
    vi.mocked(geneMarketService.getGenome).mockResolvedValue(refreshedGenome);

    await useGeneMarketStore
      .getState()
      .rateGenome('genome-1', { rating: 4, comment: 'Solid' }, { tenant_id: 'tenant-2' });

    expect(geneMarketService.rateGenome).toHaveBeenCalledWith(
      'genome-1',
      { rating: 4, comment: 'Solid' },
      { tenant_id: 'tenant-2' }
    );
    expect(geneMarketService.getGenome).toHaveBeenCalledWith('genome-1', {
      tenant_id: 'tenant-2',
    });
    expect(useGeneMarketStore.getState().genomes[0]?.avg_rating).toBe(3.5);
    expect(useGeneMarketStore.getState().currentGenome?.avg_rating).toBe(3.5);
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
