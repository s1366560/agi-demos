
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, render, waitFor } from '../../utils'
import { ProjectList } from '../../../pages/tenant/ProjectList'
import { useTenantStore } from '../../../stores/tenant'
import { projectAPI } from '../../../services/api'

vi.mock('../../../stores/tenant')
vi.mock('../../../services/api')

describe('ProjectList', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('renders list of projects', async () => {
        vi.mocked(useTenantStore).mockReturnValue({
            currentTenant: { id: 't1' }
        } as any)

        vi.mocked(projectAPI.list).mockResolvedValue({
            projects: [
                { id: 'p1', name: 'Project A', description: 'Desc A' },
                { id: 'p2', name: 'Project B', description: 'Desc B' }
            ]
        })

        render(<ProjectList />)

        await waitFor(() => {
            expect(screen.getByText('Project A')).toBeInTheDocument()
            expect(screen.getByText('Project B')).toBeInTheDocument()
        })
    })

    it('renders empty state', async () => {
        vi.mocked(useTenantStore).mockReturnValue({
            currentTenant: { id: 't1' }
        } as any)

        vi.mocked(projectAPI.list).mockResolvedValue({
            projects: []
        })

        render(<ProjectList />)

        await waitFor(() => {
            expect(screen.getByText('Create New Project')).toBeInTheDocument()
        })
    })
})
