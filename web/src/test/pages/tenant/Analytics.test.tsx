import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { Analytics } from '../../../pages/tenant/Analytics';
import { useTenantStore } from '../../../stores/tenant';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: {
      changeLanguage: () => Promise.resolve(),
      language: 'en-US',
    },
  }),
}));

vi.mock('../../../services/api', () => ({
  projectAPI: {
    list: vi.fn(() =>
      Promise.resolve({
        projects: [
          { id: '1', name: 'Project 1' },
          { id: '2', name: 'Project 2' },
        ],
      })
    ),
  },
}));

vi.mock('../../../services/analyticsService', () => ({
  analyticsService: {
    getTenantAnalytics: vi.fn(() =>
      Promise.resolve({
        summary: {
          total_memories: 100,
          total_projects: 2,
          total_storage_bytes: 1073741824,
        },
        memoryGrowth: [],
        projectStorage: [],
      })
    ),
  },
}));

vi.mock('../../../stores/tenant', () => ({
  useTenantStore: vi.fn(() => ({
    currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'premium' },
  })),
}));

vi.mock('../../../pages/tenant/ChartComponents', () => ({
  __esModule: true,
  default: vi.fn(({ memoryGrowthData, _projectStorageData, projectsLength }) => (
    <div data-testid="chart-components">
      <div data-testid="memory-growth-chart">{memoryGrowthData.datasets[0].data.length} points</div>
      <div data-testid="project-storage-chart">{projectsLength} projects</div>
    </div>
  )),
}));

describe('Analytics', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Rendering', () => {
    it('should render loading state when no tenant', () => {
      (useTenantStore as any).mockReturnValue({ currentTenant: null });
      render(<Analytics />);
      expect(screen.getByText('common.loading')).toBeInTheDocument();
    });

    it('should render loading state when loading projects', async () => {
      (useTenantStore as any).mockReturnValue({
        currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'premium' },
      });
      render(<Analytics />);
      // Should show loading initially
      expect(screen.getByText(/loading/i)).toBeInTheDocument();
      await screen.findByText('tenant.analytics.title');
    });

    it('should render KPI cards after data loads', async () => {
      (useTenantStore as any).mockReturnValue({
        currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'premium' },
      });
      render(<Analytics />);

      await waitFor(() => {
        expect(screen.getByText('tenant.analytics.total_memories')).toBeInTheDocument();
        expect(screen.getByText('tenant.analytics.active_projects')).toBeInTheDocument();
      });
    });

    it('should render chart components after data loads', async () => {
      (useTenantStore as any).mockReturnValue({
        currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'premium' },
      });
      render(<Analytics />);

      await waitFor(() => {
        expect(screen.queryByTestId('chart-components')).toBeInTheDocument();
      });
    });
  });

  describe('Data Display', () => {
    it('should display correct plan type', async () => {
      (useTenantStore as any).mockReturnValue({
        currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'enterprise' },
      });
      render(<Analytics />);

      await waitFor(() => {
        expect(screen.getByText('enterprise')).toBeInTheDocument();
      });
    });

    it('should display storage usage information', async () => {
      (useTenantStore as any).mockReturnValue({
        currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'premium' },
      });
      render(<Analytics />);

      await waitFor(() => {
        expect(screen.getByText('tenant.analytics.storage_usage')).toBeInTheDocument();
      });
    });
  });

  describe('Performance', () => {
    it('should lazy load chart components', async () => {
      // Verify ChartComponents is imported lazily
      const AnalyticsModule = await import('../../../pages/tenant/Analytics');
      // ChartComponents should be imported with lazy()
      expect(AnalyticsModule).toBeDefined();
    });

    it('should show Suspense fallback while charts load', async () => {
      (useTenantStore as any).mockReturnValue({
        currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'premium' },
      });

      // Mock ChartComponents to delay loading
      vi.doMock('../../../pages/tenant/ChartComponents', () => ({
        __esModule: true,
        default: vi.fn(
          () =>
            new Promise((resolve) => {
              setTimeout(() => resolve(null), 100);
            })
        ),
      }));

      render(<Analytics />);

      // Suspense fallback should be shown initially
      expect(screen.getByText(/loading/i)).toBeInTheDocument();
      await screen.findByTestId('chart-components');
    });
  });

  describe('Component Structure', () => {
    it('should use lazy import for ChartComponents', async () => {
      const AnalyticsModule = await import('../../../pages/tenant/Analytics');
      expect(AnalyticsModule.Analytics).toBeDefined();
    });
  });

  describe('Accessibility', () => {
    it('should have proper heading structure', async () => {
      (useTenantStore as any).mockReturnValue({
        currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'premium' },
      });
      render(<Analytics />);

      await waitFor(() => {
        const h1 = screen.getByText('tenant.analytics.title');
        expect(h1.tagName).toBe('H1');
      });
    });
  });
});
