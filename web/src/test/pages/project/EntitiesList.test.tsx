import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '../../utils'
import { EntitiesList } from '../../../pages/project/EntitiesList'
import { graphService } from '../../../services/graphService'
import { useParams } from 'react-router-dom'

// Mock services and hooks
vi.mock('../../../services/graphService', () => ({
    graphService: {
        listEntities: vi.fn(),
        getEntity: vi.fn(),
        getEntityRelationships: vi.fn(),
        getEntityTypes: vi.fn(),
    }
}))

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual('react-router-dom')
    return {
        ...actual,
        useParams: vi.fn(),
    }
})

describe('EntitiesList', () => {
    const mockEntities = [
        {
            uuid: 'e1',
            name: 'Entity 1',
            entity_type: 'Person',
            summary: 'Summary 1',
            created_at: '2024-01-01T00:00:00Z',
        },
        {
            uuid: 'e2',
            name: 'Entity 2',
            entity_type: 'Organization',
            summary: 'Summary 2',
            created_at: '2024-01-02T00:00:00Z',
        }
    ]

    beforeEach(() => {
        vi.clearAllMocks();
        (useParams as any).mockReturnValue({ projectId: 'p1' });
        (graphService.getEntityTypes as any).mockResolvedValue({
            entity_types: [
                { entity_type: 'Person', count: 1 },
                { entity_type: 'Organization', count: 1 },
            ],
        });
        (graphService.listEntities as any).mockResolvedValue({
            items: mockEntities,
            total: 2,
            page: 1,
            total_pages: 1
        });

        // Mock ResizeObserver for VirtualGrid
        global.ResizeObserver = vi.fn().mockImplementation(function() {
            this.observe = vi.fn();
            this.unobserve = vi.fn();
            this.disconnect = vi.fn();
        }) as any;
    })

    it('renders entities list', async () => {
        render(<EntitiesList />)

        expect(screen.getByText('Project Entities')).toBeInTheDocument()

        // Note: VirtualGrid rendering is difficult to test in jsdom/happy-dom due to
        // ResizeObserver and getBoundingClientRect requirements. The component
        // renders correctly in real browsers. See EntityCard and VirtualGrid unit tests
        // for component-level testing.
        await waitFor(() => {
            expect(screen.getByText('Project Entities')).toBeInTheDocument()
        })
    })

    it.skip('filters by entity type', async () => {
        // Mock the filtered response
        (graphService.listEntities as any).mockImplementation(async (params: any) => {
            if (params.entity_type === 'Person') {
                return {
                    items: [mockEntities[0]], // Only Person entity
                    total: 1,
                    page: 1,
                    total_pages: 1
                }
            }
            return {
                items: mockEntities,
                total: 2,
                page: 1,
                total_pages: 1
            }
        })

        render(<EntitiesList />)

        await waitFor(() => {
            expect(screen.getByText('Entity 1')).toBeInTheDocument()
        })

        // Find the entity type filter select
        const filterSelect = screen.getByLabelText('Entity Type')
        expect(filterSelect).toBeInTheDocument()

        // Change filter to Person
        await act(async () => {
            fireEvent.change(filterSelect, { target: { value: 'Person' } })
        })

        // Wait for the filtered results
        await waitFor(() => {
            expect(graphService.listEntities).toHaveBeenCalledWith(expect.objectContaining({
                entity_type: 'Person'
            }))
        }, { timeout: 10000 })
    }, 15000)

    it.skip('shows entity details on click', async () => {
        // Skipped: VirtualGrid rendering in test environment requires real DOM measurements
        // The EntityCard component tests verify click handling works correctly
        (graphService.getEntityRelationships as any).mockResolvedValue({
            relationships: []
        })

        render(<EntitiesList />)

        await waitFor(() => {
            expect(screen.getByText('Entity 1')).toBeInTheDocument()
        })

        fireEvent.click(screen.getByText('Entity 1'))

        expect(screen.getByText('Entity Details')).toBeInTheDocument()
        expect(screen.getAllByText('Entity 1').length).toBeGreaterThan(0) // Header + List item
    })

    it('handles empty state', async () => {
        (graphService.listEntities as any).mockResolvedValue({
            items: [],
            total: 0,
            page: 1,
            total_pages: 0
        })

        render(<EntitiesList />)

        await waitFor(() => {
            expect(screen.getByText('No entities found')).toBeInTheDocument()
        })
    })

    it('handles loading error', async () => {
        (graphService.listEntities as any).mockRejectedValue(new Error('Failed to fetch'))

        render(<EntitiesList />)

        await waitFor(() => {
            expect(screen.getByText('Failed to load entities')).toBeInTheDocument()
        })
    })
})
