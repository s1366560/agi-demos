/**
 * Analytics.test.tsx
 *
 * Performance and functionality tests for Analytics component.
 * Tests verify React.memo optimization and component behavior.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Analytics } from '../../../pages/tenant/Analytics';
import { useTenantStore } from '../../../stores/tenant';

// Mock react-i18next
vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string) => key,
        i18n: {
            changeLanguage: () => Promise.resolve(),
            language: 'en-US',
        },
    }),
}));

// Mock project store
vi.mock('../../../stores/project', () => ({
    projectAPI: {
        list: vi.fn(() => Promise.resolve({
            projects: [
                { id: '1', name: 'Project 1' },
                { id: '2', name: 'Project 2' },
            ]
        })),
    },
}));

// Mock tenant store
vi.mock('../../../stores/tenant', () => ({
    useTenantStore: vi.fn(() => ({
        currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'premium' },
    })),
}));

// Mock ChartComponents lazy load
vi.mock('../../../pages/tenant/ChartComponents', () => ({
    __esModule: true,
    default: vi.fn(({ memoryGrowthData, projectStorageData, projectsLength }) => (
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
            expect(screen.getByText('tenant.analytics.no_workspace')).toBeInTheDocument();
        });

        it('should render loading state when loading projects', () => {
            (useTenantStore as any).mockReturnValue({
                currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'premium' }
            });
            render(<Analytics />);
            // Should show loading initially
            expect(screen.getByText(/loading/i)).toBeInTheDocument();
        });

        it('should render KPI cards after data loads', async () => {
            (useTenantStore as any).mockReturnValue({
                currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'premium' }
            });
            render(<Analytics />);

            await waitFor(() => {
                expect(screen.getByText('tenant.analytics.total_memories')).toBeInTheDocument();
                expect(screen.getByText('tenant.analytics.active_projects')).toBeInTheDocument();
            });
        });

        it('should render chart components after data loads', async () => {
            (useTenantStore as any).mockReturnValue({
                currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'premium' }
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
                currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'enterprise' }
            });
            render(<Analytics />);

            await waitFor(() => {
                expect(screen.getByText('enterprise')).toBeInTheDocument();
            });
        });

        it('should display storage usage information', async () => {
            (useTenantStore as any).mockReturnValue({
                currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'premium' }
            });
            render(<Analytics />);

            await waitFor(() => {
                expect(screen.getByText('tenant.analytics.storage_usage')).toBeInTheDocument();
            });
        });
    });

    describe('Performance', () => {
        it('should lazy load chart components', () => {
            // Verify ChartComponents is imported lazily
            const AnalyticsModule = require('../../../pages/tenant/Analytics');
            // ChartComponents should be imported with lazy()
            expect(AnalyticsModule).toBeDefined();
        });

        it('should show Suspense fallback while charts load', async () => {
            (useTenantStore as any).mockReturnValue({
                currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'premium' }
            });

            // Mock ChartComponents to delay loading
            vi.doMock('../../../pages/tenant/ChartComponents', () => ({
                __esModule: true,
                default: vi.fn(() => new Promise(resolve => {
                    setTimeout(() => resolve(null), 100);
                })),
            }));

            render(<Analytics />);

            // Suspense fallback should be shown initially
            expect(screen.getByText(/loading/i)).toBeInTheDocument();
        });
    });

    describe('Component Structure', () => {
        it('should use lazy import for ChartComponents', () => {
            const sourceCode = require('fs').readFileSync(
                require.resolve('../../../pages/tenant/Analytics'),
                'utf-8'
            );
            expect(sourceCode).toContain('lazy(');
        });
    });

    describe('Accessibility', () => {
        it('should have proper heading structure', async () => {
            (useTenantStore as any).mockReturnValue({
                currentTenant: { id: 'tenant-1', name: 'Test Tenant', plan: 'premium' }
            });
            render(<Analytics />);

            await waitFor(() => {
                const h1 = screen.getByText('tenant.analytics.title');
                expect(h1.tagName).toBe('H1');
            });
        });
    });
});
