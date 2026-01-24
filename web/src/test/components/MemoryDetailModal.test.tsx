import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryDetailModal } from '../../components/MemoryDetailModal'

describe('MemoryDetailModal', () => {
    const mockOnClose = vi.fn()
    const mockMemory: any = {
        id: '1',
        title: 'Test Memory',
        content: 'Test Content',
        content_type: 'text',
        author_id: 'user1',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        project_id: 'p1',
        tags: [],
        entities: [
            { id: 'e1', name: 'Entity1', type: 'Person', properties: { role: 'Admin' }, confidence: 0.9 }
        ],
        relationships: [
            { id: 'r1', source_id: 'Entity1', target_id: 'Entity2', type: 'Knows', properties: {}, confidence: 0.8 }
        ],
        collaborators: [],
        is_public: false,
        metadata: { key: 'value' }
    }

    it('renders nothing if not open', () => {
        const { container } = render(
            <MemoryDetailModal isOpen={false} onClose={mockOnClose} memory={mockMemory} />
        )
        expect(container).toBeEmptyDOMElement()
    })

    it('renders memory details', () => {
        render(<MemoryDetailModal isOpen={true} onClose={mockOnClose} memory={mockMemory} />)

        expect(screen.getByText('记忆详情')).toBeInTheDocument()
        expect(screen.getByText('Test Memory')).toBeInTheDocument()
        expect(screen.getByText('Test Content')).toBeInTheDocument()
        expect(screen.getByText('text')).toBeInTheDocument()
        expect(screen.getByText('用户: user1')).toBeInTheDocument()
    })

    it('renders entities and relationships', () => {
        render(<MemoryDetailModal isOpen={true} onClose={mockOnClose} memory={mockMemory} />)

        expect(screen.getAllByText('Entity1').length).toBeGreaterThan(0)
        expect(screen.getByText('Person')).toBeInTheDocument()
        // Selectors might need adjustment depending on exact rendering
        // Just checking text presence is usually enough if unique
        expect(screen.getByText('Knows')).toBeInTheDocument()
    })

    it('handles download', () => {
        // Mock URL.createObjectURL
        window.URL.createObjectURL = vi.fn()
        window.URL.revokeObjectURL = vi.fn()

        render(<MemoryDetailModal isOpen={true} onClose={mockOnClose} memory={mockMemory} />)

        const downloadButton = screen.getByTitle('下载')
        fireEvent.click(downloadButton)

        expect(window.URL.createObjectURL).toHaveBeenCalled()
    })
})
