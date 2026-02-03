/**
 * GraphService Mock for Testing
 */

import { vi } from 'vitest'

export const graphService = {
    getGraphData: vi.fn(() => Promise.resolve({
        elements: {
            nodes: [
                { data: { id: 'n1', label: 'Entity', name: 'Test Entity', uuid: 'u1', entity_type: 'Person' } },
                { data: { id: 'n2', label: 'Community', name: 'Test Community', uuid: 'u2', member_count: 5 } }
            ],
            edges: [
                { data: { id: 'e1', source: 'n1', target: 'n2', label: 'MEMBER_OF' } }
            ]
        }
    })),
    getSubgraph: vi.fn(() => Promise.resolve({
        elements: {
            nodes: [
                { data: { id: 'n1', label: 'Entity', name: 'Test Entity', uuid: 'u1', entity_type: 'Person' } }
            ],
            edges: []
        }
    }))
}

vi.mock('@/services/graphService', () => ({
    graphService
}))
