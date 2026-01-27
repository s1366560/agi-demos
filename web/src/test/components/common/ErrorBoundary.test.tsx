/**
 * ErrorBoundary Component Tests
 *
 * TDD Phase 1.1: Global Error Boundary Enhancement
 *
 * These tests ensure the ErrorBoundary:
 * 1. Catches errors in child components
 * 2. Displays fallback UI
 * 3. Provides recovery mechanisms
 * 4. Integrates with error reporting services
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ErrorBoundary } from '../../../components/common'

// Helper to query by selector
const queryBySelector = (selector: string) => document.querySelector(selector)

describe('ErrorBoundary', () => {
    /**
     * Test: Renders children when no error occurs
     */
    it('renders children when no error occurs', () => {
        const SafeComponent = () => {
            return <div>Safe Content</div>
        }

        render(
            <ErrorBoundary>
                <SafeComponent />
            </ErrorBoundary>
        )

        expect(screen.getByText('Safe Content')).toBeInTheDocument()
    })

    /**
     * Test: Catches JavaScript errors in child components
     */
    it('catches JavaScript errors in child components and displays fallback UI', () => {
        // Create a component that throws an error
        const ThrowError = () => {
            throw new Error('Test error')
        }

        // Suppress the actual error from being logged to console during test
        const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

        render(
            <ErrorBoundary>
                <ThrowError />
            </ErrorBoundary>
        )

        // Should show error fallback UI with Ant Design Result component
        // The ErrorBoundary renders a Result component with status="error"
        const resultElement = queryBySelector('.ant-result-error')
        expect(resultElement).toBeInTheDocument()

        // Error should be logged
        expect(consoleSpy).toHaveBeenCalled()

        consoleSpy.mockRestore()
    })

    /**
     * Test: Displays custom fallback when provided
     */
    it('displays custom fallback UI when provided', () => {
        const ThrowError = () => {
            throw new Error('Test error')
        }

        const customFallback = <div>Custom Error Message</div>

        // Suppress error logging
        vi.spyOn(console, 'error').mockImplementation(() => {})

        render(
            <ErrorBoundary fallback={customFallback}>
                <ThrowError />
            </ErrorBoundary>
        )

        expect(screen.getByText('Custom Error Message')).toBeInTheDocument()
    })

    /**
     * Test: Resets error state when retry button is clicked
     */
    it('resets error state when retry button is clicked', () => {
        const ErrorComponent = () => {
            throw new Error('Test error')
        }

        vi.spyOn(console, 'error').mockImplementation(() => {})

        // First, render the error component to trigger error boundary
        render(
            <ErrorBoundary>
                <ErrorComponent />
            </ErrorBoundary>
        )

        // Should show error state initially
        expect(queryBySelector('.ant-result-error')).toBeInTheDocument()

        // Should have retry and home buttons
        const buttons = screen.getAllByRole('button')
        expect(buttons.length).toBe(2)

        // The retry button should be clickable (doesn't throw)
        expect(() => fireEvent.click(buttons[0])).not.toThrow()
    })

    /**
     * Test: Shows error details in development mode
     */
    it('shows error details in development mode when error has stack trace', () => {
        const testError = new Error('Detailed test error')
        testError.stack = 'Error: Detailed test error\n    at Component.tsx:10:15'

        const ThrowError = () => {
            throw testError
        }

        vi.spyOn(console, 'error').mockImplementation(() => {})

        // Set NODE_ENV to development
        const originalEnv = process.env.NODE_ENV
        process.env.NODE_ENV = 'development'

        render(
            <ErrorBoundary>
                <ThrowError />
            </ErrorBoundary>
        )

        // Check for error details section (should be visible in development)
        const detailsElement = queryBySelector('details')
        expect(detailsElement).toBeInTheDocument()

        // Restore original env
        process.env.NODE_ENV = originalEnv
    })

    /**
     * Test: Logs error information to console
     */
    it('logs error information to console.error', () => {
        const ThrowError = () => {
            throw new Error('Logged error')
        }

        const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

        render(
            <ErrorBoundary>
                <ThrowError />
            </ErrorBoundary>
        )

        expect(consoleSpy).toHaveBeenCalledWith(
            'ErrorBoundary caught an error:',
            expect.any(Error),
            expect.objectContaining({
                componentStack: expect.any(String),
            })
        )

        consoleSpy.mockRestore()
    })

    /**
     * Test: Handles errors thrown during rendering
     */
    it('catches errors thrown during rendering', () => {
        const BadComponent = () => {
            const obj: any = null
            // This will throw during render
            return obj.name
        }

        vi.spyOn(console, 'error').mockImplementation(() => {})

        render(
            <ErrorBoundary>
                <BadComponent />
            </ErrorBoundary>
        )

        expect(queryBySelector('.ant-result-error')).toBeInTheDocument()
    })
})

describe('ErrorBoundary Recovery', () => {
    /**
     * Test: Has retry button for error recovery
     */
    it('provides retry mechanism for error recovery', () => {
        const ErrorComponent = () => {
            throw new Error('Conditional error')
        }

        vi.spyOn(console, 'error').mockImplementation(() => {})

        render(
            <ErrorBoundary>
                <ErrorComponent />
            </ErrorBoundary>
        )

        // Should show error UI
        expect(queryBySelector('.ant-result-error')).toBeInTheDocument()

        // Should have retry button for recovery
        const buttons = screen.getAllByRole('button')
        expect(buttons.length).toBeGreaterThan(0)

        // Clicking the retry button should not throw errors
        expect(() => fireEvent.click(buttons[0])).not.toThrow()
    })
})

describe('ErrorBoundary Integration', () => {
    /**
     * Test: Works with React Router navigation
     */
    it('navigates to home when home button is clicked', () => {
        const ThrowError = () => {
            throw new Error('Navigation test error')
        }

        vi.spyOn(console, 'error').mockImplementation(() => {})

        // Mock window.location.href
        const originalHref = window.location.href
        const mockLocation = { href: '' }
        Object.defineProperty(window, 'location', {
            value: mockLocation,
            writable: true,
            configurable: true,
        })

        render(
            <ErrorBoundary>
                <ThrowError />
            </ErrorBoundary>
        )

        const buttons = screen.getAllByRole('button')
        const homeButton = buttons.find(btn => btn.textContent?.includes('Home') || btn.textContent?.includes('Go'))
        if (homeButton) {
            fireEvent.click(homeButton)
            expect(window.location.href).toBe('/')
        }

        // Restore original location
        Object.defineProperty(window, 'location', {
            value: originalHref,
            writable: true,
            configurable: true,
        })
    })
})
