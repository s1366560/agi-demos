import { useParams } from 'react-router-dom'

import { describe, it, expect, vi, beforeEach } from 'vitest'

import { MemoryGraph } from '../../../pages/project/MemoryGraph'
import { render, screen, fireEvent } from '../../utils'

// Mock CytoscapeGraph component
vi.mock('../../../components/graph/CytoscapeGraph', () => ({
    CytoscapeGraph: ({ onNodeClick }: any) => (
        <div data-testid="cytoscape-graph">
            <button
                onClick={() => onNodeClick({
                    uuid: 'e1',
                    name: 'Test Entity',
                    type: 'Entity',
                    summary: 'Test Summary',
                    entity_type: 'Person',
                    member_count: 5,
                    tenant_id: 't1',
                    project_id: 'p1'
                })}
            >
                Simulate Node Click
            </button>
        </div>
    )
}))

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual('react-router-dom')
    return {
        ...actual,
        useParams: vi.fn(),
    }
})

describe('MemoryGraph', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        (useParams as any).mockReturnValue({ projectId: 'p1' });
    })

    it('renders graph container', () => {
        render(<MemoryGraph />)
        expect(screen.getByTestId('cytoscape-graph')).toBeInTheDocument()
    })

    it('shows full node details', () => {
        render(<MemoryGraph />)

        // Simulate clicking a complex node
        fireEvent.click(screen.getByText('Simulate Node Click'))

        expect(screen.getByText('Test Entity')).toBeInTheDocument()
        expect(screen.getByText('Test Summary')).toBeInTheDocument()
        expect(screen.getByText('Entity')).toBeInTheDocument()
        expect(screen.getByText('Person')).toBeInTheDocument() // entity_type
        expect(screen.getByText('5 entities')).toBeInTheDocument() // member_count
        expect(screen.getByText('Tenant: t1')).toBeInTheDocument()
    })

    it('closes details panel', () => {
        render(<MemoryGraph />)
        fireEvent.click(screen.getByText('Simulate Node Click'))
        expect(screen.getByText('Test Entity')).toBeInTheDocument()

        // Find close button (using material symbol text)
        fireEvent.click(screen.getByText('close'))

        expect(screen.queryByText('Test Entity')).not.toBeInTheDocument()
    })
})
