import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { EditUserModal } from '@/components/tenant/EditUserModal'

describe('EditUserModal - Component Tests', () => {
    const mockUser = {
        id: 'user-1',
        email: 'test@example.com',
        name: 'Test User',
        role: 'member' as const,
        created_at: '2024-01-01T00:00:00Z',
        last_login: '2024-12-20T10:00:00Z',
        is_active: true
    }

    const mockOnClose = vi.fn()
    const mockOnSave = vi.fn()

    beforeEach(() => {
        vi.clearAllMocks()
    })

    describe('Modal Rendering', () => {
        it('does not render when isOpen is false', () => {
            const { container } = render(
                <EditUserModal
                    user={mockUser}
                    isOpen={false}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="project"
                    contextId="project-1"
                />
            )

            expect(container.firstChild).toBeNull()
        })

        it('renders modal when isOpen is true', () => {
            render(
                <EditUserModal
                    user={mockUser}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="project"
                    contextId="project-1"
                />
            )

            expect(screen.getByText('Edit User')).toBeInTheDocument()
        })

        it('displays user information correctly', () => {
            render(
                <EditUserModal
                    user={mockUser}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="project"
                    contextId="project-1"
                />
            )

            expect(screen.getByText('Test User')).toBeInTheDocument()
            expect(screen.getByText('test@example.com')).toBeInTheDocument()
            expect(screen.getByText('1/1/2024')).toBeInTheDocument() // Join date
            expect(screen.getByText('12/20/2024')).toBeInTheDocument() // Last login
        })

        it('shows "从未" for last login when never logged in', () => {
            const userWithoutLogin = { ...mockUser, last_login: undefined }

            render(
                <EditUserModal
                    user={userWithoutLogin}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="project"
                    contextId="project-1"
                />
            )

            expect(screen.getByText('Never')).toBeInTheDocument()
        })
    })

    describe('Role Selection', () => {
        it('displays correct roles for project context', () => {
            render(
                <EditUserModal
                    user={mockUser}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="project"
                    contextId="project-1"
                />
            )

            expect(screen.getByText('Admin')).toBeInTheDocument()
            expect(screen.getByText('Editor')).toBeInTheDocument()
            expect(screen.getByText('Viewer')).toBeInTheDocument()
        })

        it('displays correct roles for tenant context', () => {
            render(
                <EditUserModal
                    user={mockUser}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="tenant"
                    contextId="tenant-1"
                />
            )

            expect(screen.getByText('Owner')).toBeInTheDocument()
            expect(screen.getByText('Admin')).toBeInTheDocument()
            expect(screen.getByText('Member')).toBeInTheDocument()
        })

        it('disables role selection for owner role', () => {
            const ownerUser = { ...mockUser, role: 'owner' as const }

            render(
                <EditUserModal
                    user={ownerUser}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="tenant"
                    contextId="tenant-1"
                />
            )

            expect(screen.getByText('Owner role cannot be changed')).toBeInTheDocument()
        })
    })

    describe('User Interactions', () => {
        it('closes modal when cancel button is clicked', () => {
            render(
                <EditUserModal
                    user={mockUser}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="project"
                    contextId="project-1"
                />
            )

            const cancelButton = screen.getByText('Cancel')
            fireEvent.click(cancelButton)

            expect(mockOnClose).toHaveBeenCalledTimes(1)
        })

        it('closes modal when X button is clicked', () => {
            render(
                <EditUserModal
                    user={mockUser}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="project"
                    contextId="project-1"
                />
            )

            const closeButton = screen.getByRole('button', { name: '' }) // X icon button
            fireEvent.click(closeButton)

            expect(mockOnClose).toHaveBeenCalledTimes(1)
        })

        it('updates role when select value changes', () => {
            const adminUser = { ...mockUser, role: 'admin' as const }

            render(
                <EditUserModal
                    user={adminUser}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="project"
                    contextId="project-1"
                />
            )

            const selectElement = screen.getByRole('combobox')
            expect(selectElement).toHaveValue('admin')

            fireEvent.change(selectElement, { target: { value: 'viewer' } })
            expect(selectElement).toHaveValue('viewer')
        })
    })

    describe('Save Functionality', () => {
        it('calls onSave with correct parameters when save button is clicked', async () => {
            mockOnSave.mockResolvedValueOnce(undefined)

            render(
                <EditUserModal
                    user={mockUser}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="project"
                    contextId="project-1"
                />
            )

            const saveButton = screen.getByText('Save')
            fireEvent.click(saveButton)

            await waitFor(() => {
                expect(mockOnSave).toHaveBeenCalledWith('user-1', { role: 'member' })
            })
        })

        it('shows loading state while saving', async () => {
            mockOnSave.mockImplementation(
                () => new Promise(resolve => setTimeout(() => resolve(undefined), 100))
            )

            render(
                <EditUserModal
                    user={mockUser}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="project"
                    contextId="project-1"
                />
            )

            const saveButton = screen.getByText('Save')
            fireEvent.click(saveButton)

            // Check for loading state
            await waitFor(() => {
                expect(screen.getByText('Saving...')).toBeInTheDocument()
            })
        })

        it('closes modal after successful save', async () => {
            mockOnSave.mockResolvedValueOnce(undefined)

            render(
                <EditUserModal
                    user={mockUser}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="project"
                    contextId="project-1"
                />
            )

            const saveButton = screen.getByText('Save')
            fireEvent.click(saveButton)

            await waitFor(() => {
                expect(mockOnClose).toHaveBeenCalled()
            })
        })

        it('does not close modal on save error', async () => {
            mockOnSave.mockRejectedValueOnce(new Error('Update failed'))

            const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

            render(
                <EditUserModal
                    user={mockUser}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="project"
                    contextId="project-1"
                />
            )

            const saveButton = screen.getByText('Save')
            fireEvent.click(saveButton)

            await waitFor(() => {
                expect(mockOnSave).toHaveBeenCalled()
                expect(mockOnClose).not.toHaveBeenCalled()
            })

            consoleSpy.mockRestore()
        })

        it('disables save button for owner role', () => {
            const ownerUser = { ...mockUser, role: 'owner' as const }

            render(
                <EditUserModal
                    user={ownerUser}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="tenant"
                    contextId="tenant-1"
                />
            )

            const saveButton = screen.getByText('Save')
            expect(saveButton).toBeDisabled()
        })
    })

    describe('Role Change Before Save', () => {
        it('calls onSave with new role after changing role and saving', async () => {
            mockOnSave.mockResolvedValueOnce(undefined)

            render(
                <EditUserModal
                    user={mockUser}
                    isOpen={true}
                    onClose={mockOnClose}
                    onSave={mockOnSave}
                    context="project"
                    contextId="project-1"
                />
            )

            const selectElement = screen.getByRole('combobox')
            fireEvent.change(selectElement, { target: { value: 'viewer' } })

            const saveButton = screen.getByText('Save')
            fireEvent.click(saveButton)

            await waitFor(() => {
                expect(mockOnSave).toHaveBeenCalledWith('user-1', { role: 'viewer' })
            })
        })
    })
})
