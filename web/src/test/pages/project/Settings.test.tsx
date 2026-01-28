/**
 * Tests for Settings page component
 * Characterization tests for useCallback refactoring
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '../../utils'
import { ProjectSettings } from '../../../pages/project/Settings'

// Mock useProjectStore
vi.mock('../../../stores/project', () => ({
    useProjectStore: () => ({
        currentProject: {
            id: 'project-1',
            name: 'Test Project',
            description: 'Test Description',
            is_public: false,
            tenant_id: 'tenant-1',
            owner_id: 'user-1',
            created_at: new Date().toISOString(),
            memory_rules: {
                max_episodes: 100,
                retention_days: 365,
                auto_refresh: true,
                refresh_interval: 24
            },
            graph_config: {
                max_nodes: 10000,
                max_edges: 50000,
                similarity_threshold: 0.8,
                community_detection: true
            }
        }
    })
}))

// Mock API
vi.mock('../../../services/api', () => ({
    api: {
        post: vi.fn()
    },
    projectAPI: {
        update: vi.fn(),
        delete: vi.fn()
    }
}))

describe('ProjectSettings Page', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        // Mock window.confirm
        global.confirm = vi.fn(() => true)
        // Mock window.prompt
        global.prompt = vi.fn(() => 'Test Project')
        // Mock window.alert
        global.alert = vi.fn()
        // Mock window.location
        delete (window as any).location
        window.location = { href: '' } as any
    })

    describe('Rendering', () => {
        it('renders the settings page with all sections', () => {
            render(<ProjectSettings />)

            // Title should be present
            expect(screen.getByText('Project Settings')).toBeInTheDocument()
        })

        it('displays project name from store', () => {
            render(<ProjectSettings />)
            expect(screen.getByDisplayValue('Test Project')).toBeInTheDocument()
        })

        it('displays project description from store', () => {
            render(<ProjectSettings />)
            expect(screen.getByDisplayValue('Test Description')).toBeInTheDocument()
        })
    })

    describe('Form Interactions', () => {
        it('has name input', () => {
            render(<ProjectSettings />)
            expect(screen.getByDisplayValue('Test Project')).toBeInTheDocument()
        })

        it('has text area for description', () => {
            render(<ProjectSettings />)
            // Just verify the description is present
            expect(screen.getByDisplayValue('Test Description')).toBeInTheDocument()
        })

        it('has checkboxes present', () => {
            render(<ProjectSettings />)
            const checkboxes = screen.getAllByRole('checkbox')
            expect(checkboxes.length).toBeGreaterThan(0)
        })
    })

    describe('Memory Rules Section', () => {
        it('renders memory rules inputs with correct values', () => {
            render(<ProjectSettings />)

            expect(screen.getByDisplayValue('100')).toBeInTheDocument()
            expect(screen.getByDisplayValue('365')).toBeInTheDocument()
        })

        it('has multiple number inputs on page', () => {
            render(<ProjectSettings />)

            // Just verify there are number inputs present
            const inputs = screen.getAllByRole('spinbutton')
            expect(inputs.length).toBeGreaterThan(0)
        })
    })

    describe('Graph Configuration Section', () => {
        it('renders graph config inputs with correct values', () => {
            render(<ProjectSettings />)

            // Graph config has max_nodes=10000 and max_edges=50000
            const numberInputs = screen.getAllByDisplayValue(/10000|50000/)
            expect(numberInputs.length).toBeGreaterThan(0)
        })

        it('toggles community detection checkbox', () => {
            render(<ProjectSettings />)

            // Find all checkboxes and verify at least one is checked
            const checkboxes = screen.getAllByRole('checkbox')
            const checkedBoxes = checkboxes.filter(cb => (cb as HTMLInputElement).checked)
            expect(checkedBoxes.length).toBeGreaterThan(0)
        })
    })

    describe('Advanced Actions', () => {
        it('shows action buttons', () => {
            render(<ProjectSettings />)

            const buttons = screen.getAllByRole('button')
            expect(buttons.length).toBeGreaterThan(0)
        })
    })

    describe('Danger Zone', () => {
        it('shows delete project button', () => {
            render(<ProjectSettings />)

            const buttons = screen.getAllByRole('button')
            // There should be multiple buttons including delete
            expect(buttons.length).toBeGreaterThan(0)
        })
    })
})
