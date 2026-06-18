import { MemoryRouter } from 'react-router-dom';

import { message, Modal } from 'antd';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { GeneDetail } from '@/pages/tenant/GeneDetail';
import { GeneMarket } from '@/pages/tenant/GeneMarket';
import { GenomeDetail } from '@/pages/tenant/GenomeDetail';

import type {
  EvolutionEventResponse,
  GeneResponse,
  GeneReview,
  GenomeResponse,
} from '@/services/geneMarketService';

const navigateMock = vi.hoisted(() => vi.fn());
const paramsMock = vi.hoisted(() => ({
  geneId: 'gene-1',
  genomeId: 'genome-1',
  tenantId: 'tenant-1',
}));

const actionsMock = vi.hoisted(() => ({
  clearError: vi.fn(),
  createGene: vi.fn(),
  createGenome: vi.fn(),
  createGeneReview: vi.fn(),
  deleteGene: vi.fn(),
  deleteGenome: vi.fn(),
  deleteGeneReview: vi.fn(),
  fetchGeneReviews: vi.fn(),
  fetchGenomeGenes: vi.fn(),
  getGene: vi.fn(),
  getGenome: vi.fn(),
  installGene: vi.fn(),
  listGeneEvolutionEvents: vi.fn(),
  listGenes: vi.fn(),
  listGenomes: vi.fn(),
  publishGene: vi.fn(),
  publishGenome: vi.fn(),
  rateGene: vi.fn(),
  rateGenome: vi.fn(),
  reset: vi.fn(),
  setActiveTab: vi.fn(),
  setCurrentGene: vi.fn(),
  setCurrentGenome: vi.fn(),
  unpublishGene: vi.fn(),
  unpublishGenome: vi.fn(),
  updateGene: vi.fn(),
  updateGenome: vi.fn(),
}));

const stateMock = vi.hoisted(() => ({
  activeTab: 'genes' as 'genes' | 'genomes',
  currentGene: null as GeneResponse | null,
  currentGenome: null as GenomeResponse | null,
  currentGenomeGenes: [] as GeneResponse[],
  currentGenomeGenesLoading: false,
  evolutionEvents: [] as EvolutionEventResponse[],
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
  useCurrentGenomeGenes: () => stateMock.currentGenomeGenes,
  useCurrentGenomeGenesLoading: () => stateMock.currentGenomeGenesLoading,
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

const evolutionEvent = (
  overrides: Partial<EvolutionEventResponse> = {}
): EvolutionEventResponse => ({
  created_at: '2026-06-17T00:00:00Z',
  details: {},
  event_type: 'learned',
  from_version: null,
  gene_id: 'gene-1',
  gene_name: 'Code Review',
  gene_slug: 'code-review',
  genome_id: null,
  id: 'event-1',
  instance_id: 'instance-1',
  payload: {},
  status: 'completed',
  to_version: null,
  trigger: null,
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
    stateMock.currentGenomeGenes = [gene()];
    stateMock.currentGenomeGenesLoading = false;
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
    actionsMock.fetchGenomeGenes.mockResolvedValue([gene()]);
    actionsMock.getGene.mockResolvedValue(gene());
    actionsMock.getGenome.mockResolvedValue(genome());
    actionsMock.listGeneEvolutionEvents.mockResolvedValue(undefined);
    actionsMock.listGenes.mockResolvedValue(undefined);
    actionsMock.listGenomes.mockResolvedValue(undefined);
    actionsMock.createGeneReview.mockResolvedValue(undefined);
    actionsMock.createGene.mockResolvedValue(gene({ id: 'gene-new' }));
    actionsMock.createGenome.mockResolvedValue(genome({ id: 'genome-new' }));
    actionsMock.deleteGene.mockResolvedValue(undefined);
    actionsMock.deleteGenome.mockResolvedValue(undefined);
    actionsMock.deleteGeneReview.mockResolvedValue(undefined);
    actionsMock.publishGene.mockResolvedValue(gene({ is_published: true }));
    actionsMock.publishGenome.mockResolvedValue(genome({ is_published: true }));
    actionsMock.rateGene.mockResolvedValue(undefined);
    actionsMock.rateGenome.mockResolvedValue(undefined);
    actionsMock.unpublishGene.mockResolvedValue(gene({ is_published: false }));
    actionsMock.unpublishGenome.mockResolvedValue(genome({ is_published: false }));
    actionsMock.updateGene.mockResolvedValue(gene({ name: 'Code Review Pro' }));
    actionsMock.updateGenome.mockResolvedValue(genome({ name: 'Review Pack Pro' }));
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

  it('shows list failures as a retryable marketplace error', async () => {
    stateMock.genes = [];
    stateMock.geneTotal = 0;
    stateMock.error = 'Failed to list genes';

    render(
      <MemoryRouter>
        <GeneMarket />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(actionsMock.listGenes).toHaveBeenCalledWith({
        page: 1,
        page_size: 20,
        tenant_id: 'tenant-1',
      });
    });
    expect(screen.getByText('Could not load marketplace data')).toBeInTheDocument();
    expect(screen.getByText('Failed to list genes')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(actionsMock.listGenes).toHaveBeenCalledTimes(2);
    });
    expect(actionsMock.listGenes).toHaveBeenLastCalledWith({
      page: 1,
      page_size: 20,
      tenant_id: 'tenant-1',
    });
  });

  it('creates a draft gene from the marketplace publish action', async () => {
    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes']}>
        <GeneMarket />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole('button', { name: 'tenant.genes.publishButton' }));

    expect(await screen.findByText('Create Gene Draft')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Code Review Assistant' },
    });
    fireEvent.change(screen.getByLabelText('Slug'), {
      target: { value: 'code-review-assistant' },
    });
    fireEvent.change(screen.getByLabelText('Category'), {
      target: { value: 'tool' },
    });
    fireEvent.change(screen.getByLabelText('Short description'), {
      target: { value: 'Reviews pull requests' },
    });
    fireEvent.change(screen.getByLabelText('Description'), {
      target: { value: 'Automates code review checks for tenant agents.' },
    });
    fireEvent.change(screen.getByLabelText('Tags'), {
      target: { value: 'review, quality, review' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Draft' }));

    await waitFor(() => {
      expect(actionsMock.createGene).toHaveBeenCalledWith(
        {
          name: 'Code Review Assistant',
          slug: 'code-review-assistant',
          tenant_id: 'tenant-1',
          category: 'tool',
          version: '1.0.0',
          short_description: 'Reviews pull requests',
          description: 'Automates code review checks for tenant agents.',
          visibility: 'public',
          tags: ['review', 'quality'],
          source: 'manual',
        },
        { tenant_id: 'tenant-1' }
      );
    });
    expect(navigateMock).toHaveBeenCalledWith('gene-new');
  });

  it('creates a draft genome from the marketplace genomes tab action', async () => {
    stateMock.activeTab = 'genomes';
    stateMock.genomes = [genome()];
    stateMock.genomeTotal = 1;

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes']}>
        <GeneMarket />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole('button', { name: 'Create Genome' }));

    expect((await screen.findAllByText('Create Genome Draft')).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Review Pack' },
    });
    fireEvent.change(screen.getByLabelText('Slug'), {
      target: { value: 'review-pack' },
    });
    fireEvent.change(screen.getByLabelText('Short description'), {
      target: { value: 'Review automation bundle' },
    });
    fireEvent.change(screen.getByLabelText('Description'), {
      target: { value: 'Combines reviewer genes for tenant projects.' },
    });
    fireEvent.change(screen.getByLabelText('Included gene slugs'), {
      target: { value: 'code-review, test-writer, code-review' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Genome Draft' }));

    await waitFor(() => {
      expect(actionsMock.createGenome).toHaveBeenCalledWith(
        {
          name: 'Review Pack',
          slug: 'review-pack',
          tenant_id: 'tenant-1',
          visibility: 'public',
          gene_slugs: ['code-review', 'test-writer'],
          short_description: 'Review automation bundle',
          description: 'Combines reviewer genes for tenant projects.',
        },
        { tenant_id: 'tenant-1' }
      );
    });
    expect(navigateMock).toHaveBeenCalledWith('./genomes/genome-new');
  });

  it('lists genomes with search, visibility, and publish filters', async () => {
    stateMock.activeTab = 'genomes';
    stateMock.genomes = [genome()];
    stateMock.genomeTotal = 1;

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes']}>
        <GeneMarket />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(actionsMock.listGenomes).toHaveBeenCalledWith({
        page: 1,
        page_size: 20,
        tenant_id: 'tenant-1',
      });
    });

    fireEvent.change(screen.getByLabelText('Search genomes...'), {
      target: { value: 'review' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Filter genomes by visibility' }));
    fireEvent.click(screen.getByText('Public'));
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Filter by publish status' }));
    const publishedOptions = screen.getAllByText('Published');
    fireEvent.click(publishedOptions[publishedOptions.length - 1] as HTMLElement);

    await waitFor(() => {
      expect(actionsMock.listGenomes).toHaveBeenLastCalledWith({
        page: 1,
        page_size: 20,
        tenant_id: 'tenant-1',
        search: 'review',
        visibility: 'public',
        is_published: true,
      });
    });
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

  it('surfaces install failures from the gene store', async () => {
    const messageErrorSpy = vi.spyOn(message, 'error').mockImplementation(vi.fn());
    stateMock.currentGene = gene();
    stateMock.error = 'Install API failed';
    actionsMock.installGene.mockRejectedValue(new Error('Network Error'));

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/gene-1']}>
        <GeneDetail />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'tenant.genes.installAction' }));
    fireEvent.change(screen.getByLabelText('tenant.genes.instanceId'), {
      target: { value: 'instance-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));

    await waitFor(() => {
      expect(actionsMock.installGene).toHaveBeenCalledWith(
        'instance-1',
        { gene_id: 'gene-1', config: {} },
        { tenant_id: 'tenant-1' }
      );
    });
    expect(messageErrorSpy).toHaveBeenCalledWith('Install API failed');
  });

  it('does not submit install requests with invalid JSON config', async () => {
    const messageErrorSpy = vi.spyOn(message, 'error').mockImplementation(vi.fn());
    stateMock.currentGene = gene();

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/gene-1']}>
        <GeneDetail />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'tenant.genes.installAction' }));
    fireEvent.change(screen.getByLabelText('tenant.genes.instanceId'), {
      target: { value: 'instance-1' },
    });
    fireEvent.change(screen.getByLabelText('tenant.genes.configOverride'), {
      target: { value: '{not-json' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));

    await waitFor(() => {
      expect(messageErrorSpy).toHaveBeenCalledWith('Invalid JSON format');
    });
    expect(actionsMock.installGene).not.toHaveBeenCalled();
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

  it('refreshes reviews with the visible page size after creating a review', async () => {
    const messageSuccessSpy = vi.spyOn(message, 'success').mockImplementation(vi.fn());
    stateMock.currentGene = gene();

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
      expect(actionsMock.createGeneReview).toHaveBeenCalledWith(
        'gene-1',
        { rating: 5, content: 'Useful and reliable.' },
        { tenant_id: 'tenant-1' }
      );
    });
    expect(actionsMock.fetchGeneReviews).toHaveBeenLastCalledWith('gene-1', 1, 5, {
      tenant_id: 'tenant-1',
    });
    expect(messageSuccessSpy).toHaveBeenCalledWith('gene.reviewSubmitSuccess');
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

  it('refreshes the previous reviews page after deleting the last item on a later page', async () => {
    const messageSuccessSpy = vi.spyOn(message, 'success').mockImplementation(vi.fn());
    vi.spyOn(Modal, 'confirm').mockImplementation((config) => {
      void config.onOk?.();
      return {
        destroy: vi.fn(),
        update: vi.fn(),
      };
    });
    stateMock.currentGene = gene();
    stateMock.reviews = [review()];
    stateMock.reviewsTotal = 10;

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/gene-1']}>
        <GeneDetail />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(actionsMock.fetchGeneReviews).toHaveBeenCalledWith('gene-1', 1, 5, {
        tenant_id: 'tenant-1',
      });
    });
    actionsMock.fetchGeneReviews.mockClear();

    fireEvent.click(screen.getByText('2'));

    await waitFor(() => {
      expect(actionsMock.fetchGeneReviews).toHaveBeenCalledWith('gene-1', 2, 5, {
        tenant_id: 'tenant-1',
      });
    });
    actionsMock.fetchGeneReviews.mockClear();

    fireEvent.click(screen.getByRole('button', { name: 'gene.deleteReview' }));

    await waitFor(() => {
      expect(actionsMock.deleteGeneReview).toHaveBeenCalledWith('gene-1', 'review-1', {
        tenant_id: 'tenant-1',
      });
    });
    expect(actionsMock.fetchGeneReviews).toHaveBeenLastCalledWith('gene-1', 1, 5, {
      tenant_id: 'tenant-1',
    });
    expect(messageSuccessSpy).toHaveBeenCalledWith('gene.reviewDeleteSuccess');
  });

  it('paginates reviews without refetching gene detail or resetting state', async () => {
    stateMock.currentGene = gene();
    stateMock.reviews = [review()];
    stateMock.reviewsTotal = 10;

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/gene-1']}>
        <GeneDetail />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(actionsMock.getGene).toHaveBeenCalledWith('gene-1', { tenant_id: 'tenant-1' });
      expect(actionsMock.listGeneEvolutionEvents).toHaveBeenCalledWith('gene-1', {
        tenant_id: 'tenant-1',
      });
      expect(actionsMock.fetchGeneReviews).toHaveBeenCalledWith('gene-1', 1, 5, {
        tenant_id: 'tenant-1',
      });
    });

    actionsMock.getGene.mockClear();
    actionsMock.listGeneEvolutionEvents.mockClear();
    actionsMock.fetchGeneReviews.mockClear();
    actionsMock.reset.mockClear();
    actionsMock.clearError.mockClear();

    fireEvent.click(screen.getByText('2'));

    await waitFor(() => {
      expect(actionsMock.fetchGeneReviews).toHaveBeenCalledWith('gene-1', 2, 5, {
        tenant_id: 'tenant-1',
      });
    });
    expect(actionsMock.getGene).not.toHaveBeenCalled();
    expect(actionsMock.listGeneEvolutionEvents).not.toHaveBeenCalled();
    expect(actionsMock.reset).not.toHaveBeenCalled();
    expect(actionsMock.clearError).not.toHaveBeenCalled();
  });

  it('renders gene evolution events with backend event labels', async () => {
    stateMock.currentGene = gene();
    stateMock.evolutionEvents = [
      evolutionEvent({ event_type: 'learned', gene_name: 'Learned review gene' }),
    ];

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/gene-1']}>
        <GeneDetail />
      </MemoryRouter>
    );

    expect(await screen.findByText('Learned')).toBeInTheDocument();
    expect(screen.getByText('Learned review gene')).toBeInTheDocument();
    expect(screen.queryByText(/^learned$/)).not.toBeInTheDocument();
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

  it('updates genes from the detail edit dialog', async () => {
    const messageSuccessSpy = vi.spyOn(message, 'success').mockImplementation(vi.fn());
    stateMock.currentGene = gene();

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/gene-1']}>
        <GeneDetail />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Code Review Pro' },
    });
    fireEvent.change(screen.getByLabelText('Slug'), {
      target: { value: 'code-review-pro' },
    });
    fireEvent.change(screen.getByLabelText('Version'), {
      target: { value: '1.1.0' },
    });
    fireEvent.change(screen.getByLabelText('Tags'), {
      target: { value: 'review, quality, review' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));

    await waitFor(() => {
      expect(actionsMock.updateGene).toHaveBeenCalledWith(
        'gene-1',
        {
          name: 'Code Review Pro',
          slug: 'code-review-pro',
          category: 'tool',
          version: '1.1.0',
          short_description: 'Review code',
          description: 'Automates code review checks',
          visibility: 'public',
          tags: ['review', 'quality'],
        },
        { tenant_id: 'tenant-1' }
      );
    });
    expect(messageSuccessSpy).toHaveBeenCalledWith('Gene updated successfully');
  });

  it('deletes genes from the detail action bar after confirmation', async () => {
    const messageSuccessSpy = vi.spyOn(message, 'success').mockImplementation(vi.fn());
    vi.spyOn(Modal, 'confirm').mockImplementation((config) => {
      void config.onOk?.();
      return {
        destroy: vi.fn(),
        update: vi.fn(),
      };
    });
    stateMock.currentGene = gene();

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/gene-1']}>
        <GeneDetail />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));

    await waitFor(() => {
      expect(actionsMock.deleteGene).toHaveBeenCalledWith('gene-1', { tenant_id: 'tenant-1' });
    });
    expect(messageSuccessSpy).toHaveBeenCalledWith('Gene deleted successfully');
    expect(navigateMock).toHaveBeenCalledWith(-1);
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
    expect(actionsMock.fetchGenomeGenes).toHaveBeenCalledWith(['code-review'], {
      tenant_id: 'tenant-1',
    });
    expect(messageSuccessSpy).toHaveBeenCalledWith('Genome unpublished successfully');
  });

  it('deletes genomes from the detail action bar after confirmation', async () => {
    const messageSuccessSpy = vi.spyOn(message, 'success').mockImplementation(vi.fn());
    vi.spyOn(Modal, 'confirm').mockImplementation((config) => {
      void config.onOk?.();
      return {
        destroy: vi.fn(),
        update: vi.fn(),
      };
    });
    stateMock.currentGenome = genome({ is_published: true });

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/genomes/genome-1']}>
        <GenomeDetail />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));

    await waitFor(() => {
      expect(actionsMock.deleteGenome).toHaveBeenCalledWith('genome-1', {
        tenant_id: 'tenant-1',
      });
    });
    expect(messageSuccessSpy).toHaveBeenCalledWith('Genome deleted successfully');
    expect(navigateMock).toHaveBeenCalledWith(-1);
  });

  it('updates genomes from the detail edit dialog', async () => {
    const messageSuccessSpy = vi.spyOn(message, 'success').mockImplementation(vi.fn());
    stateMock.currentGenome = genome({
      config_override: { mode: 'balanced' },
      gene_slugs: ['code-review', 'test-writer'],
    });

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/genomes/genome-1']}>
        <GenomeDetail />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Review Pack Pro' },
    });
    fireEvent.change(screen.getByLabelText('Slug'), {
      target: { value: 'review-pack-pro' },
    });
    fireEvent.change(screen.getByLabelText('Included gene slugs'), {
      target: { value: 'code-review, deploy-check, code-review' },
    });
    fireEvent.change(screen.getByLabelText('Configuration Override (JSON)'), {
      target: { value: '{"mode":"strict"}' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));

    await waitFor(() => {
      expect(actionsMock.updateGenome).toHaveBeenCalledWith(
        'genome-1',
        {
          name: 'Review Pack Pro',
          slug: 'review-pack-pro',
          short_description: 'Review workflow',
          description: 'Review workflow bundle',
          visibility: 'public',
          gene_slugs: ['code-review', 'deploy-check'],
          config_override: { mode: 'strict' },
        },
        { tenant_id: 'tenant-1' }
      );
    });
    expect(messageSuccessSpy).toHaveBeenCalledWith('Genome updated successfully');
  });

  it('rates genomes from the detail action bar', async () => {
    const messageSuccessSpy = vi.spyOn(message, 'success').mockImplementation(vi.fn());
    stateMock.currentGenome = genome({ is_published: true });

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/genomes/genome-1']}>
        <GenomeDetail />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Rate' }));
    fireEvent.change(screen.getByLabelText('tenant.genes.comment'), {
      target: { value: 'Useful bundle.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));

    await waitFor(() => {
      expect(actionsMock.rateGenome).toHaveBeenCalledWith(
        'genome-1',
        { rating: 5, comment: 'Useful bundle.' },
        { tenant_id: 'tenant-1' }
      );
    });
    expect(messageSuccessSpy).toHaveBeenCalledWith('Genome rating submitted successfully');
  });

  it('surfaces genome rating failures from the store', async () => {
    const messageErrorSpy = vi.spyOn(message, 'error').mockImplementation(vi.fn());
    stateMock.currentGenome = genome({ is_published: true });
    stateMock.error = 'Genome rating API failed';
    actionsMock.rateGenome.mockRejectedValue(new Error('Network Error'));

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/genomes/genome-1']}>
        <GenomeDetail />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Rate' }));
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));

    await waitFor(() => {
      expect(messageErrorSpy).toHaveBeenCalledWith('Genome rating API failed');
    });
  });

  it('does not refetch genome genes when only genome metadata changes', async () => {
    stateMock.currentGenome = genome({ is_published: false, gene_slugs: ['code-review'] });

    const { rerender } = render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/genomes/genome-1']}>
        <GenomeDetail />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(actionsMock.fetchGenomeGenes).toHaveBeenCalledWith(['code-review'], {
        tenant_id: 'tenant-1',
      });
    });
    actionsMock.fetchGenomeGenes.mockClear();

    stateMock.currentGenome = genome({ is_published: true, gene_slugs: ['code-review'] });
    rerender(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/genomes/genome-1']}>
        <GenomeDetail />
      </MemoryRouter>
    );

    expect(actionsMock.fetchGenomeGenes).not.toHaveBeenCalled();
  });

  it('shows unavailable genome gene references without using the marketplace gene list', async () => {
    stateMock.currentGenome = genome({ gene_slugs: ['test-writer', 'code-review'] });
    stateMock.currentGenomeGenes = [gene({ slug: 'code-review', name: 'Code Review' })];
    stateMock.genes = [gene({ slug: 'market-only', name: 'Marketplace Only' })];

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-1/genes/genomes/genome-1']}>
        <GenomeDetail />
      </MemoryRouter>
    );

    expect(await screen.findByText('Some referenced genes are unavailable')).toBeInTheDocument();
    expect(screen.getByText('test-writer')).toBeInTheDocument();
    expect(screen.getByText('Code Review')).toBeInTheDocument();
    expect(screen.queryByText('Marketplace Only')).not.toBeInTheDocument();
    expect(actionsMock.fetchGenomeGenes).toHaveBeenCalledWith(['test-writer', 'code-review'], {
      tenant_id: 'tenant-1',
    });
    expect(actionsMock.listGenes).not.toHaveBeenCalled();
  });
});
