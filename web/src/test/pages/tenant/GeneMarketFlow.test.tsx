import { MemoryRouter } from 'react-router-dom';

import { message, Modal } from 'antd';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { GeneDetail } from '@/pages/tenant/GeneDetail';
import { GeneMarket } from '@/pages/tenant/GeneMarket';
import { GenomeDetail } from '@/pages/tenant/GenomeDetail';

import type { GeneResponse, GeneReview, GenomeResponse } from '@/services/geneMarketService';

const navigateMock = vi.hoisted(() => vi.fn());
const paramsMock = vi.hoisted(() => ({
  geneId: 'gene-1',
  genomeId: 'genome-1',
  tenantId: 'tenant-1',
}));

const actionsMock = vi.hoisted(() => ({
  clearError: vi.fn(),
  createGeneReview: vi.fn(),
  deleteGeneReview: vi.fn(),
  fetchGeneReviews: vi.fn(),
  getGene: vi.fn(),
  getGenome: vi.fn(),
  installGene: vi.fn(),
  listGeneEvolutionEvents: vi.fn(),
  listGenes: vi.fn(),
  listGenomes: vi.fn(),
  publishGene: vi.fn(),
  publishGenome: vi.fn(),
  rateGene: vi.fn(),
  reset: vi.fn(),
  setActiveTab: vi.fn(),
  setCurrentGene: vi.fn(),
  setCurrentGenome: vi.fn(),
  unpublishGene: vi.fn(),
  unpublishGenome: vi.fn(),
}));

const stateMock = vi.hoisted(() => ({
  activeTab: 'genes' as 'genes' | 'genomes',
  currentGene: null as GeneResponse | null,
  currentGenome: null as GenomeResponse | null,
  evolutionEvents: [] as unknown[],
  geneTotal: 0,
  genes: [] as GeneResponse[],
  genomeTotal: 0,
  genomes: [] as GenomeResponse[],
  isLoading: false,
  error: null as string | null,
  reviews: [] as GeneReview[],
  reviewsLoading: false,
  reviewsTotal: 0,
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
    useParams: () => paramsMock,
  };
});

vi.mock('@/stores/tenant', () => ({
  useCurrentTenant: () => ({ id: 'tenant-1' }),
}));

vi.mock('@/stores/geneMarket', () => ({
  useActiveTab: () => stateMock.activeTab,
  useCurrentGene: () => stateMock.currentGene,
  useCurrentGenome: () => stateMock.currentGenome,
  useEvolutionEvents: () => stateMock.evolutionEvents,
  useGeneMarketError: () => stateMock.error,
  useGeneMarketActions: () => actionsMock,
  useGeneMarketLoading: () => stateMock.isLoading,
  useGeneMarketStore: {
    getState: () => ({ error: stateMock.error }),
  },
  useGeneReviews: () => stateMock.reviews,
  useGeneReviewsLoading: () => stateMock.reviewsLoading,
  useGeneReviewsTotal: () => stateMock.reviewsTotal,
  useGeneTotal: () => stateMock.geneTotal,
  useGenes: () => stateMock.genes,
  useGenomeTotal: () => stateMock.genomeTotal,
  useGenomes: () => stateMock.genomes,
}));

const gene = (overrides: Partial<GeneResponse> = {}): GeneResponse => ({
  avg_rating: 4,
  category: 'tool',
  created_at: '2026-06-17T00:00:00Z',
  created_by: 'user-1',
  created_by_instance_id: null,
  dependencies: [],
  description: 'Automates code review checks',
  effectiveness_score: null,
  icon: null,
  id: 'gene-1',
  install_count: 7,
  is_featured: false,
  is_published: true,
  manifest: {},
  name: 'Code Review',
  parent_gene_id: null,
  review_status: null,
  short_description: 'Review code',
  slug: 'code-review',
  source: 'manual',
  source_ref: null,
  synergies: [],
  tags: ['quality'],
  tenant_id: 'tenant-1',
  updated_at: null,
  version: '1.0.0',
  visibility: 'public',
  ...overrides,
});

const review = (overrides: Partial<GeneReview> = {}): GeneReview => ({
  content: 'This helped the team ship faster.',
  created_at: '2026-06-17T00:00:00Z',
  gene_id: 'gene-1',
  id: 'review-1',
  rating: 5,
  user_id: 'user-1',
  ...overrides,
});

const genome = (overrides: Partial<GenomeResponse> = {}): GenomeResponse => ({
  avg_rating: 4,
  config_override: {},
  created_at: '2026-06-17T00:00:00Z',
  created_by: 'user-1',
  description: 'Review workflow bundle',
  gene_slugs: ['code-review'],
  icon: null,
  id: 'genome-1',
  install_count: 3,
  is_featured: false,
  is_published: true,
  name: 'Review Pack',
  short_description: 'Review workflow',
  slug: 'review-pack',
  tenant_id: 'tenant-1',
  updated_at: null,
  visibility: 'public',
  ...overrides,
});

describe('Gene marketplace rating flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    paramsMock.geneId = 'gene-1';
    paramsMock.genomeId = 'genome-1';
    paramsMock.tenantId = 'tenant-1';
    stateMock.activeTab = 'genes';
    stateMock.currentGene = null;
    stateMock.currentGenome = null;
    stateMock.evolutionEvents = [];
    stateMock.geneTotal = 1;
    stateMock.genes = [gene()];
    stateMock.genomeTotal = 0;
    stateMock.genomes = [];
    stateMock.isLoading = false;
    stateMock.error = null;
    stateMock.reviews = [];
    stateMock.reviewsLoading = false;
    stateMock.reviewsTotal = 0;

    actionsMock.fetchGeneReviews.mockResolvedValue(undefined);
    actionsMock.getGene.mockResolvedValue(gene());
    actionsMock.getGenome.mockResolvedValue(genome());
    actionsMock.listGeneEvolutionEvents.mockResolvedValue(undefined);
    actionsMock.listGenes.mockResolvedValue(undefined);
    actionsMock.listGenomes.mockResolvedValue(undefined);
    actionsMock.createGeneReview.mockResolvedValue(undefined);
    actionsMock.deleteGeneReview.mockResolvedValue(undefined);
    actionsMock.publishGene.mockResolvedValue(gene({ is_published: true }));
    actionsMock.publishGenome.mockResolvedValue(genome({ is_published: true }));
    actionsMock.rateGene.mockResolvedValue(undefined);
    actionsMock.unpublishGene.mockResolvedValue(gene({ is_published: false }));
    actionsMock.unpublishGenome.mockResolvedValue(genome({ is_published: false }));
  });

  it('routes card rating to the detail rating dialog instead of submitting a default rating', async () => {
    render(
      <MemoryRouter>
        <GeneMarket />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole('button', { name: 'tenant.genes.actions.rate' }));

    expect(actionsMock.rateGene).not.toHaveBeenCalled();
    expect(navigateMock).toHaveBeenCalledWith('gene-1?rate=1');
  });

  it('opens the rating modal from the rate query parameter', async () => {
    stateMock.currentGene = gene();

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/gene-1?rate=1']}>
        <GeneDetail />
      </MemoryRouter>
    );

    expect(await screen.findByText('tenant.genes.rateGene')).toBeInTheDocument();
    expect(actionsMock.rateGene).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(actionsMock.getGene).toHaveBeenCalledWith('gene-1', { tenant_id: 'tenant-1' });
    });
  });

  it('surfaces rating submission failures from the gene store', async () => {
    const messageErrorSpy = vi.spyOn(message, 'error').mockImplementation(vi.fn());
    stateMock.currentGene = gene();
    stateMock.error = 'Rating API failed';
    actionsMock.rateGene.mockRejectedValue(new Error('Network Error'));

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/gene-1?rate=1']}>
        <GeneDetail />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'OK' }));

    await waitFor(() => {
      expect(messageErrorSpy).toHaveBeenCalledWith('Rating API failed');
    });
  });

  it('surfaces review submission failures from the gene store', async () => {
    const messageErrorSpy = vi.spyOn(message, 'error').mockImplementation(vi.fn());
    stateMock.currentGene = gene();
    stateMock.error = 'Review API failed';
    actionsMock.createGeneReview.mockRejectedValue(new Error('Network Error'));

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/gene-1']}>
        <GeneDetail />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'gene.writeReview' }));
    fireEvent.change(screen.getByLabelText('gene.reviewContent'), {
      target: { value: 'Useful and reliable.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));

    await waitFor(() => {
      expect(messageErrorSpy).toHaveBeenCalledWith('Review API failed');
    });
  });

  it('surfaces review deletion failures from the gene store', async () => {
    const messageErrorSpy = vi.spyOn(message, 'error').mockImplementation(vi.fn());
    vi.spyOn(Modal, 'confirm').mockImplementation((config) => {
      void config.onOk?.();
      return {
        destroy: vi.fn(),
        update: vi.fn(),
      };
    });
    stateMock.currentGene = gene();
    stateMock.error = 'Delete API failed';
    stateMock.reviews = [review()];
    stateMock.reviewsTotal = 1;
    actionsMock.deleteGeneReview.mockRejectedValue(new Error('Network Error'));

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/gene-1']}>
        <GeneDetail />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'gene.deleteReview' }));

    await waitFor(() => {
      expect(messageErrorSpy).toHaveBeenCalledWith('Delete API failed');
    });
  });

  it('publishes draft genes from the detail action bar', async () => {
    const messageSuccessSpy = vi.spyOn(message, 'success').mockImplementation(vi.fn());
    stateMock.currentGene = gene({ is_published: false });

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/gene-1']}>
        <GeneDetail />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Publish' }));

    await waitFor(() => {
      expect(actionsMock.publishGene).toHaveBeenCalledWith('gene-1', { tenant_id: 'tenant-1' });
    });
    expect(messageSuccessSpy).toHaveBeenCalledWith('Gene published successfully');
  });

  it('unpublishes published genomes from the detail action bar', async () => {
    const messageSuccessSpy = vi.spyOn(message, 'success').mockImplementation(vi.fn());
    stateMock.currentGenome = genome({ is_published: true });

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/genomes/genome-1']}>
        <GenomeDetail />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Unpublish' }));

    await waitFor(() => {
      expect(actionsMock.unpublishGenome).toHaveBeenCalledWith('genome-1', {
        tenant_id: 'tenant-1',
      });
    });
    expect(actionsMock.listGenes).toHaveBeenCalledWith({
      tenant_id: 'tenant-1',
      slugs: ['code-review'],
      page_size: 1,
    });
    expect(messageSuccessSpy).toHaveBeenCalledWith('Genome unpublished successfully');
  });
});
