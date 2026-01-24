import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '../../utils'
import { EnhancedSearch } from '../../../pages/project/EnhancedSearch'
import { graphService } from '../../../services/graphService'
import { useParams } from 'react-router-dom'

// Mock CytoscapeGraph component to avoid canvas issues in test environment
vi.mock('../../../components/CytoscapeGraph', () => ({
    CytoscapeGraph: () => null
}))

// Mock useProjectStore
vi.mock('../../../stores/project', () => ({
    useProjectStore: () => ({
        currentProject: null
    })
}))

vi.mock('../../../services/graphService', () => ({
    graphService: {
        getGraphData: vi.fn(),
        advancedSearch: vi.fn(),
        searchByGraphTraversal: vi.fn(),
        searchByCommunity: vi.fn(),
        searchTemporal: vi.fn(),
        searchWithFacets: vi.fn(),
    }
}))

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual('react-router-dom')
    return {
        ...actual,
        useParams: vi.fn(),
    }
})

describe('EnhancedSearch', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        (useParams as any).mockReturnValue({ projectId: 'p1' });
    })

    describe('Search Mode Buttons', () => {
        it('renders all 5 search mode buttons', () => {
            render(<EnhancedSearch />)
            expect(screen.getByRole('button', { name: /Semantic Search/i })).toBeInTheDocument()
            expect(screen.getByRole('button', { name: /Graph Traversal/i })).toBeInTheDocument()
            expect(screen.getByRole('button', { name: /Temporal Search/i })).toBeInTheDocument()
            expect(screen.getByRole('button', { name: /Faceted Search/i })).toBeInTheDocument()
            expect(screen.getByRole('button', { name: /Community Search/i })).toBeInTheDocument()
        })

        it('switches to Graph Traversal mode', () => {
            render(<EnhancedSearch />)
            fireEvent.click(screen.getByRole('button', { name: /Graph Traversal/i }))
            expect(screen.getByPlaceholderText(/Enter start entity UUID/i)).toBeInTheDocument()
        })

        it('switches to Temporal Search mode', () => {
            render(<EnhancedSearch />)
            fireEvent.click(screen.getByRole('button', { name: /Temporal Search/i }))
            expect(screen.getByText('Time Range')).toBeInTheDocument()
        })

        it('switches to Faceted Search mode', () => {
            render(<EnhancedSearch />)
            fireEvent.click(screen.getByRole('button', { name: /Faceted Search/i }))
            expect(screen.getByText('Entity Types')).toBeInTheDocument()
        })

        it('switches to Community Search mode', () => {
            render(<EnhancedSearch />)
            fireEvent.click(screen.getByRole('button', { name: /Community Search/i }))
            expect(screen.getByPlaceholderText(/Enter community UUID/i)).toBeInTheDocument()
        })
    })

    describe('Semantic Search', () => {
        it('performs semantic search', async () => {
            (graphService.advancedSearch as any).mockResolvedValue({
                results: [{ content: 'Test Result', score: 0.9, metadata: { type: 'episode', name: 'Test' }, source: 'episode' }],
                total: 1
            })

            render(<EnhancedSearch />)
            const searchInput = screen.getByPlaceholderText(/Search memories by keyword/i)
            fireEvent.change(searchInput, { target: { value: 'test query' } })

            const retrieveButton = screen.getByRole('button', { name: /Retrieve/i })
            fireEvent.click(retrieveButton)

            await waitFor(() => {
                expect(graphService.advancedSearch).toHaveBeenCalledWith(expect.objectContaining({
                    query: 'test query'
                }))
            })
        })
    })

    describe('Graph Traversal Search', () => {
        it('shows graph traversal options', () => {
            render(<EnhancedSearch />)
            fireEvent.click(screen.getByRole('button', { name: /Graph Traversal/i }))

            expect(screen.getByText('Max Depth')).toBeInTheDocument()
            expect(screen.getByText('Relationship Types')).toBeInTheDocument()
        })

        it('performs graph traversal search', async () => {
            (graphService.searchByGraphTraversal as any).mockResolvedValue({
                results: [{ content: 'Result 1', score: 0.9, metadata: { type: 'entity', name: 'Test Entity' }, source: 'graph' }]
            })

            render(<EnhancedSearch />)
            fireEvent.click(screen.getByRole('button', { name: /Graph Traversal/i }))

            const uuidInput = screen.getByPlaceholderText(/Enter start entity UUID/i)
            fireEvent.change(uuidInput, { target: { value: 'uuid-123' } })

            const retrieveButton = screen.getByRole('button', { name: /Retrieve/i })
            fireEvent.click(retrieveButton)

            await waitFor(() => {
                expect(graphService.searchByGraphTraversal).toHaveBeenCalledWith(expect.objectContaining({
                    start_entity_uuid: 'uuid-123',
                    max_depth: 2
                }))
            })
        })
    })

    describe('Temporal Search', () => {
        it('shows temporal search options', () => {
            render(<EnhancedSearch />)
            fireEvent.click(screen.getByRole('button', { name: /Temporal Search/i }))

            expect(screen.getByText('Time Range')).toBeInTheDocument()
            expect(screen.getByRole('radio', { name: 'All Time' })).toBeInTheDocument()
            expect(screen.getByRole('radio', { name: 'Last 30 Days' })).toBeInTheDocument()
        })

        it('performs temporal search', async () => {
            (graphService.searchTemporal as any).mockResolvedValue({
                results: [{ content: 'Temporal Result', score: 0.8, metadata: { type: 'episode' }, source: 'temporal' }]
            })

            render(<EnhancedSearch />)
            fireEvent.click(screen.getByRole('button', { name: /Temporal Search/i }))

            const searchInput = screen.getByPlaceholderText(/Search memories by keyword/i)
            fireEvent.change(searchInput, { target: { value: 'test' } })

            const retrieveButton = screen.getByRole('button', { name: /Retrieve/i })
            fireEvent.click(retrieveButton)

            await waitFor(() => {
                expect(graphService.searchTemporal).toHaveBeenCalled()
            })
        })
    })

    describe('Faceted Search', () => {
        it('shows faceted search options', () => {
            render(<EnhancedSearch />)
            fireEvent.click(screen.getByRole('button', { name: /Faceted Search/i }))

            expect(screen.getByText('Entity Types')).toBeInTheDocument()
            expect(screen.getByText('Tags')).toBeInTheDocument()
        })

        it('toggles entity types', () => {
            render(<EnhancedSearch />)
            fireEvent.click(screen.getByRole('button', { name: /Faceted Search/i }))

            const personButton = screen.getByRole('button', { name: 'Person' })
            fireEvent.click(personButton)

            // Should toggle selection
            expect(personButton).toHaveClass(/bg-blue-600/)
        })

        it('performs faceted search', async () => {
            (graphService.searchWithFacets as any).mockResolvedValue({
                results: [{ content: 'Faceted Result', score: 0.7, metadata: { type: 'entity' }, source: 'faceted' }]
            })

            render(<EnhancedSearch />)
            fireEvent.click(screen.getByRole('button', { name: /Faceted Search/i }))

            // Select an entity type
            fireEvent.click(screen.getByRole('button', { name: 'Person' }))

            const searchInput = screen.getByPlaceholderText(/Search memories by keyword/i)
            fireEvent.change(searchInput, { target: { value: 'test' } })

            const retrieveButton = screen.getByRole('button', { name: /Retrieve/i })
            fireEvent.click(retrieveButton)

            await waitFor(() => {
                expect(graphService.searchWithFacets).toHaveBeenCalledWith(expect.objectContaining({
                    query: 'test',
                    entity_types: ['Person']
                }))
            })
        })
    })

    describe('Community Search', () => {
        it('shows community search options', () => {
            render(<EnhancedSearch />)
            fireEvent.click(screen.getByRole('button', { name: /Community Search/i }))

            expect(screen.getByPlaceholderText(/Enter community UUID/i)).toBeInTheDocument()
            expect(screen.getByText('Include Episodes')).toBeInTheDocument()
        })

        it('performs community search', async () => {
            (graphService.searchByCommunity as any).mockResolvedValue({
                results: [{ content: 'Community Result', score: 0.85, metadata: { type: 'entity' }, source: 'community' }]
            })

            render(<EnhancedSearch />)
            fireEvent.click(screen.getByRole('button', { name: /Community Search/i }))

            const uuidInput = screen.getByPlaceholderText(/Enter community UUID/i)
            fireEvent.change(uuidInput, { target: { value: 'community-123' } })

            const retrieveButton = screen.getByRole('button', { name: /Retrieve/i })
            fireEvent.click(retrieveButton)

            await waitFor(() => {
                expect(graphService.searchByCommunity).toHaveBeenCalledWith(expect.objectContaining({
                    community_uuid: 'community-123'
                }))
            })
        })
    })

    describe('Search History', () => {
        it('saves search to history after successful search', async () => {
            (graphService.advancedSearch as any).mockResolvedValue({
                results: [{ content: 'Test', score: 0.9, metadata: { type: 'episode' }, source: 'test' }],
                total: 1
            })

            render(<EnhancedSearch />)

            const searchInput = screen.getByPlaceholderText(/Search memories by keyword/i)
            fireEvent.change(searchInput, { target: { value: 'history test' } })

            const retrieveButton = screen.getByRole('button', { name: /Retrieve/i })
            fireEvent.click(retrieveButton)

            await waitFor(() => {
                expect(graphService.advancedSearch).toHaveBeenCalled()
            })

            // History button should appear
            await waitFor(() => {
                expect(screen.getByRole('button', { name: /History/ })).toBeInTheDocument()
            })
        })
    })

    describe('Export Functionality', () => {
        it('shows export button when results exist', async () => {
            (graphService.advancedSearch as any).mockResolvedValue({
                results: [{ content: 'Test', score: 0.9, metadata: { type: 'episode' }, source: 'test' }],
                total: 1
            })

            render(<EnhancedSearch />)

            const searchInput = screen.getByPlaceholderText(/Search memories by keyword/i)
            fireEvent.change(searchInput, { target: { value: 'test' } })

            const retrieveButton = screen.getByRole('button', { name: /Retrieve/i })
            fireEvent.click(retrieveButton)

            await waitFor(() => {
                expect(screen.getByRole('button', { name: /Export/i })).toBeInTheDocument()
            })
        })
    })
})
