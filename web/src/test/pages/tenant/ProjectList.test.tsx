
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { ProjectList } from '../../../pages/tenant/ProjectList'
import { projectAPI } from '../../../services/api'
import { useTenantStore } from '../../../stores/tenant'
import { screen, render, waitFor } from '../../utils'

import type { Project } from '../../../types/memory'

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

        const mockProjects: Project[] = [
            {
                id: 'p1',
                tenant_id: 't1',
                name: 'Project A',
                description: 'Desc A',
                owner_id: 'user1',
                member_ids: [],
                memory_rules: {
                    max_episodes: 1000,
                    retention_days: 30,
                    auto_refresh: true,
                    refresh_interval: 300
                },
                graph_config: {
                    max_nodes: 500,
                    max_edges: 1000,
                    similarity_threshold: 0.8,
                    community_detection: true
                },
                is_public: false,
                created_at: '2024-01-01T00:00:00Z'
            },
            {
                id: 'p2',
                tenant_id: 't1',
                name: 'Project B',
                description: 'Desc B',
                owner_id: 'user1',
                member_ids: [],
                memory_rules: {
                    max_episodes: 1000,
                    retention_days: 30,
                    auto_refresh: true,
                    refresh_interval: 300
                },
                graph_config: {
                    max_nodes: 500,
                    max_edges: 1000,
                    similarity_threshold: 0.8,
                    community_detection: true
                },
                is_public: false,
                created_at: '2024-01-01T00:00:00Z'
            }
        ]

        vi.mocked(projectAPI.list).mockResolvedValue({
            projects: mockProjects,
            total: 2,
            page: 1,
            page_size: 10
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
            projects: [],
            total: 0,
            page: 1,
            page_size: 10
        })

        render(<ProjectList />)

        await waitFor(() => {
            expect(screen.getByText('Create New Project')).toBeInTheDocument()
        })
    })
})
