import type { ReactNode } from 'react';

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { InstanceGenes } from '@/pages/tenant/InstanceGenes';
import { geneMarketService } from '@/services/geneMarketService';

const navigateMock = vi.hoisted(() => vi.fn());

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
  useLazyMessage: () => ({ error: vi.fn(), success: vi.fn() }),
}));

const mockService = vi.mocked(geneMarketService);

describe('InstanceGenes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockService.listInstanceGenes.mockResolvedValue({
      active_total: 0,
      has_more: false,
      items: [],
      limit: 25,
      offset: 0,
      total: 0,
      usage_total: 0,
    });
    mockService.listGenes.mockResolvedValue({
      genes: [],
      page: 1,
      page_size: 20,
      total: 0,
    });
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
});
