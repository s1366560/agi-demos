
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, render } from '../utils'
import { ProjectLayout } from '../../layouts/ProjectLayout'
import { useParams } from 'react-router-dom'

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual('react-router-dom')
    return {
        ...actual,
        useParams: vi.fn(),
    }
})

vi.mock('../../components/WorkspaceSwitcher', () => ({
    WorkspaceSwitcher: () => <div>MockSwitcher</div>
}))

describe('ProjectLayout', () => {
    beforeEach(() => {
        (useParams as any).mockReturnValue({ projectId: 'p1' })
    })

    it('renders project navigation items', () => {
        render(<ProjectLayout />)

        expect(screen.getByText('Overview')).toBeInTheDocument()
        expect(screen.getByText('Memories')).toBeInTheDocument()
        expect(screen.getByText('Knowledge Graph')).toBeInTheDocument()
    })
})
