import type { ReactNode } from 'react';

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { InstanceGenes } from '@/pages/tenant/InstanceGenes';
import { geneMarketService } from '@/services/geneMarketService';

import type {
  GeneListResponse,
  GeneResponse,
  InstanceGeneListResponse,
  InstanceGeneResponse,
} from '@/services/geneMarketService';

const navigateMock = vi.hoisted(() => vi.fn());
const lazyMessageMock = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
    useParams: () => ({ tenantId: 'tenant-1', instanceId: 'instance-1' }),
  };
});

vi.mock('@/hooks/useDebounce', () => ({
  useDebounce: (value: unknown) => value,
}));

vi.mock('@/services/geneMarketService', () => ({
  geneMarketService: {
    installGene: vi.fn(),
    listGenes: vi.fn(),
    listInstanceGenes: vi.fn(),
    uninstallGene: vi.fn(),
  },
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyButton: ({
    children,
    disabled,
    icon,
    onClick,
  }: {
    children?: ReactNode;
    disabled?: boolean;
    icon?: ReactNode;
    onClick?: () => void;
  }) => (
    <button disabled={disabled} onClick={onClick} type="button">
      {icon}
      {children}
    </button>
  ),
  LazyEmpty: ({ description }: { description?: ReactNode }) => <div>{description}</div>,
  LazyModal: ({
    children,
    open,
    title,
  }: {
    children?: ReactNode;
    open?: boolean;
    title?: ReactNode;
  }) =>
    open ? (
      <div role="dialog">
        <h2>{title}</h2>
        {children}
      </div>
    ) : null,
  LazyPopconfirm: ({ children }: { children?: ReactNode }) => <>{children}</>,
  LazySpin: () => <div>loading</div>,
  useLazyMessage: () => lazyMessageMock,
}));

const mockService = vi.mocked(geneMarketService);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, reject, resolve };
}

const installedGene = (
  overrides: Partial<InstanceGeneResponse> = {}
): InstanceGeneResponse => ({
  config_snapshot: {},
  created_at: '2026-06-17T00:00:00Z',
  gene_category: 'qa',
  gene_description: 'Installed gene',
  gene_id: 'gene-1',
  gene_name: 'Installed Gene',
  genome_id: null,
  id: 'installed-1',
  installed_at: '2026-06-17T00:00:00Z',
  installed_version: '1.0.0',
  instance_id: 'instance-1',
  status: 'installed',
  usage_count: 0,
  ...overrides,
});

const installedGeneList = (
  items: InstanceGeneResponse[],
  overrides: Partial<InstanceGeneListResponse> = {}
): InstanceGeneListResponse => ({
  active_total: items.length,
  has_more: false,
  items,
  limit: 25,
  offset: 0,
  total: items.length,
  usage_total: items.reduce((total, item) => total + item.usage_count, 0),
  ...overrides,
});

const gene = (overrides: Partial<GeneResponse> = {}): GeneResponse => ({
  avg_rating: null,
  category: 'qa',
  created_at: '2026-06-17T00:00:00Z',
  created_by: 'user-1',
  created_by_instance_id: null,
  dependencies: [],
  description: 'Available gene',
  effectiveness_score: null,
  icon: null,
  id: 'gene-1',
  install_count: 0,
  is_featured: false,
  is_published: true,
  manifest: {},
  name: 'Available Gene',
  parent_gene_id: null,
  review_status: null,
  short_description: 'Available gene',
  slug: 'available-gene',
  source: 'self_created',
  source_ref: null,
  synergies: [],
  tags: [],
  tenant_id: 'tenant-1',
  updated_at: null,
  version: '1.0.0',
  visibility: 'public',
  ...overrides,
});

const geneList = (
  genes: GeneResponse[],
  overrides: Partial<GeneListResponse> = {}
): GeneListResponse => ({
  genes,
  page: 1,
  page_size: 20,
  total: genes.length,
  ...overrides,
});

describe('InstanceGenes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockService.listInstanceGenes.mockResolvedValue(installedGeneList([]));
    mockService.listGenes.mockResolvedValue(geneList([]));
  });

  it('requests installed gene search from the backend', async () => {
    render(<InstanceGenes />);

    await waitFor(() => {
      expect(mockService.listInstanceGenes).toHaveBeenCalledWith('instance-1', {
        limit: 25,
        offset: 0,
        search: undefined,
        tenant_id: 'tenant-1',
      });
    });

    fireEvent.change(screen.getByPlaceholderText('tenant.instances.genes.searchPlaceholder'), {
      target: { value: 'review' },
    });

    await waitFor(() => {
      expect(mockService.listInstanceGenes).toHaveBeenCalledWith('instance-1', {
        limit: 25,
        offset: 0,
        search: 'review',
        tenant_id: 'tenant-1',
      });
    });
  });

  it('requests installable genes with server-side installed exclusion', async () => {
    render(<InstanceGenes />);

    fireEvent.click(screen.getByRole('button', { name: /tenant.instances.genes.installGene/ }));

    await waitFor(() => {
      expect(mockService.listGenes).toHaveBeenCalledWith({
        exclude_installed_instance_id: 'instance-1',
        is_published: true,
        page: 1,
        page_size: 20,
        search: undefined,
        tenant_id: 'tenant-1',
      });
    });
  });

  it('ignores stale installed gene search responses', async () => {
    const staleRequest = deferred<InstanceGeneListResponse>();
    const freshRequest = deferred<InstanceGeneListResponse>();
    mockService.listInstanceGenes
      .mockReturnValueOnce(staleRequest.promise)
      .mockReturnValueOnce(freshRequest.promise);

    render(<InstanceGenes />);

    fireEvent.change(screen.getByPlaceholderText('tenant.instances.genes.searchPlaceholder'), {
      target: { value: 'fresh' },
    });

    await waitFor(() => {
      expect(mockService.listInstanceGenes).toHaveBeenCalledTimes(2);
    });

    await act(async () => {
      freshRequest.resolve(installedGeneList([installedGene({ gene_name: 'Fresh Gene' })]));
      await freshRequest.promise;
    });

    expect(await screen.findByText('Fresh Gene')).toBeInTheDocument();

    await act(async () => {
      staleRequest.resolve(installedGeneList([installedGene({ gene_name: 'Stale Gene' })]));
      await staleRequest.promise;
    });

    await waitFor(() => {
      expect(screen.queryByText('Stale Gene')).not.toBeInTheDocument();
    });
    expect(screen.getByText('Fresh Gene')).toBeInTheDocument();
  });

  it('ignores stale installable gene search responses', async () => {
    const staleRequest = deferred<GeneListResponse>();
    const freshRequest = deferred<GeneListResponse>();
    mockService.listGenes.mockReturnValueOnce(staleRequest.promise).mockReturnValueOnce(freshRequest.promise);

    render(<InstanceGenes />);

    fireEvent.click(screen.getByRole('button', { name: /tenant.instances.genes.installGene/ }));
    await waitFor(() => {
      expect(mockService.listGenes).toHaveBeenCalledTimes(1);
    });

    fireEvent.change(screen.getByPlaceholderText('tenant.instances.genes.availableSearchPlaceholder'), {
      target: { value: 'fresh' },
    });
    await waitFor(() => {
      expect(mockService.listGenes).toHaveBeenCalledTimes(2);
    });

    await act(async () => {
      freshRequest.resolve(geneList([gene({ id: 'fresh-gene', name: 'Fresh Available Gene' })]));
      await freshRequest.promise;
    });

    expect(await screen.findByText('Fresh Available Gene')).toBeInTheDocument();

    await act(async () => {
      staleRequest.resolve(geneList([gene({ id: 'stale-gene', name: 'Stale Available Gene' })]));
      await staleRequest.promise;
    });

    await waitFor(() => {
      expect(screen.queryByText('Stale Available Gene')).not.toBeInTheDocument();
    });
    expect(screen.getByText('Fresh Available Gene')).toBeInTheDocument();
  });
});
