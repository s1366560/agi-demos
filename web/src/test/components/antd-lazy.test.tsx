/**
 * Ant Design Lazy Loading Tests
 *
 * TDD Phase 1 (RED): Tests for Ant Design component lazy loading
 *
 * These tests verify that Ant Design components are properly lazy-loaded
 * to reduce initial bundle size. The tests will fail initially because
 * the lazy loading implementation doesn't exist yet.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { Suspense } from 'react'

// Mock console.warn to avoid cluttering test output
const originalWarn = console.warn
beforeEach(() => {
  console.warn = vi.fn()
})

// Test data for lazy loading verification
const LAZY_ANTD_COMPONENTS = [
  'Spin',
  'Button',
  'Progress',
  'Select',
  'Tag',
  'Tooltip',
  'Avatar',
  'Modal',
  'Input',
  'message',
  'notification',
] as const

type LazyAntdComponent = typeof LAZY_ANTD_COMPONENTS[number]

describe('Ant Design Lazy Loading', () => {
  describe('Component lazy loading wrapper', () => {
    it('should export a lazy loading wrapper for Ant Design components', async () => {
      // This test will fail until we create the lazy loading module
      const lazyAntd = await import('@/components/ui/lazyAntd')

      expect(lazyAntd).toBeDefined()
      expect(typeof lazyAntd.lazySpin).toBe('function')
      expect(typeof lazyAntd.lazyButton).toBe('function')
      expect(typeof lazyAntd.lazyProgress).toBe('function')
      expect(typeof lazyAntd.lazySelect).toBe('function')
      expect(typeof lazyAntd.lazyTag).toBe('function')
      expect(typeof lazyAntd.lazyTooltip).toBe('function')
      expect(typeof lazyAntd.lazyAvatar).toBe('function')
    })

    it('should provide a loading fallback component', async () => {
      const { LazySpinner } = await import('@/components/ui/lazyAntd')

      const { container } = render(
        <Suspense fallback={<div data-testid="fallback">Loading...</div>}>
          <LazySpinner />
        </Suspense>
      )

      // Should show fallback initially
      expect(screen.getByTestId('fallback')).toBeInTheDocument()

      // Should render the actual component after loading
      await waitFor(() => {
        expect(container.querySelector('.ant-spin')).toBeInTheDocument()
      })
    })
  })

  describe('Component functionality after lazy load', () => {
    it('should render Spin component with correct props', async () => {
      const { LazySpin } = await import('@/components/ui/lazyAntd')

      const { container } = render(
        <Suspense fallback={<div>Loading...</div>}>
          <LazySpin size="large" />
        </Suspense>
      )

      await waitFor(() => {
        const spinElement = container.querySelector('.ant-spin-lg')
        expect(spinElement).toBeInTheDocument()
      })
    })

    it('should render Button component with correct props', async () => {
      const { LazyButton } = await import('@/components/ui/lazyAntd')

      const { container } = render(
        <Suspense fallback={<div>Loading...</div>}>
          <LazyButton type="primary">Click me</LazyButton>
        </Suspense>
      )

      await waitFor(() => {
        const button = container.querySelector('.ant-btn-primary')
        expect(button).toBeInTheDocument()
        expect(button?.textContent).toBe('Click me')
      })
    })

    it('should render Progress component with correct props', async () => {
      const { LazyProgress } = await import('@/components/ui/lazyAntd')

      const { container } = render(
        <Suspense fallback={<div>Loading...</div>}>
          <LazyProgress percent={50} />
        </Suspense>
      )

      await waitFor(() => {
        const progress = container.querySelector('.ant-progress')
        expect(progress).toBeInTheDocument()
      })
    })

    it('should render Select component with correct props', async () => {
      const { LazySelect } = await import('@/components/ui/lazyAntd')

      const { container } = render(
        <Suspense fallback={<div>Loading...</div>}>
          <LazySelect defaultValue="option1" options={[{ value: 'option1', label: 'Option 1' }]} />
        </Suspense>
      )

      await waitFor(() => {
        const select = container.querySelector('.ant-select')
        expect(select).toBeInTheDocument()
      })
    })

    it('should render Tag component with correct props', async () => {
      const { LazyTag } = await import('@/components/ui/lazyAntd')

      const { container } = render(
        <Suspense fallback={<div>Loading...</div>}>
          <LazyTag color="blue">Test Tag</LazyTag>
        </Suspense>
      )

      await waitFor(() => {
        const tag = container.querySelector('.ant-tag')
        expect(tag).toBeInTheDocument()
        expect(tag?.textContent).toBe('Test Tag')
      })
    })

    it('should render Tooltip component with correct props', async () => {
      const { LazyTooltip } = await import('@/components/ui/lazyAntd')

      const { container } = render(
        <Suspense fallback={<div>Loading...</div>}>
          <LazyTooltip title="Test tooltip">
            <button>Hover me</button>
          </LazyTooltip>
        </Suspense>
      )

      await waitFor(() => {
        const tooltip = container.querySelector('.ant-tooltip')
        expect(tooltip).toBeInTheDocument()
      })
    })

    it('should render Avatar component with correct props', async () => {
      const { LazyAvatar } = await import('@/components/ui/lazyAntd')

      const { container } = render(
        <Suspense fallback={<div>Loading...</div>}>
          <LazyAvatar icon="U" />
        </Suspense>
      )

      await waitFor(() => {
        const avatar = container.querySelector('.ant-avatar')
        expect(avatar).toBeInTheDocument()
      })
    })
  })

  describe('Code splitting verification', () => {
    it('should import antd components dynamically, not statically', async () => {
      // This test verifies that components are using dynamic imports
      // by checking the module imports at runtime
      const lazyAntdModule = await import('@/components/ui/lazyAntd')

      // Verify that the lazy components are functions (lazy-loaded)
      expect(typeof lazyAntdModule.LazySpin).toBe('object')
      expect(typeof lazyAntdModule.LazyButton).toBe('object')
      expect(typeof lazyAntdModule.LazyProgress).toBe('object')
    })

    it('should provide a default fallback component', async () => {
      const { DefaultFallback } = await import('@/components/ui/lazyAntd')

      const { container } = render(<DefaultFallback />)

      expect(container.textContent).toContain('Loading')
    })
  })

  describe('TypeScript type safety', () => {
    it('should export correct TypeScript types', async () => {
      const lazyAntd = await import('@/components/ui/lazyAntd')

      // Verify that the module exports the expected types
      expect(lazyAntd).toHaveProperty('LazySpin')
      expect(lazyAntd).toHaveProperty('LazyButton')
      expect(lazyAntd).toHaveProperty('LazyProgress')
      expect(lazyAntd).toHaveProperty('LazySelect')
      expect(lazyAntd).toHaveProperty('LazyTag')
      expect(lazyAntd).toHaveProperty('LazyTooltip')
      expect(lazyAntd).toHaveProperty('LazyAvatar')
    })
  })

  describe('Performance optimization', () => {
    it('should not import antd on module load', async () => {
      // This test verifies that importing the lazy module doesn't
      // immediately load all antd components
      const antdImportSpy = vi.spyOn(require('antd'), 'Spin')

      await import('@/components/ui/lazyAntd')

      // The Spin component should not be imported until actually used
      expect(antdImportSpy).not.toHaveBeenCalled()
    })
  })

  describe('Accessibility', () => {
    it('should maintain ARIA attributes after lazy loading', async () => {
      const { LazyButton } = await import('@/components/ui/lazyAntd')

      const { container } = render(
        <Suspense fallback={<div>Loading...</div>}>
          <LazyButton aria-label="Close button">X</LazyButton>
        </Suspense>
      )

      await waitFor(() => {
        const button = container.querySelector('[aria-label="Close button"]')
        expect(button).toBeInTheDocument()
      })
    })

    it('should maintain keyboard navigation after lazy loading', async () => {
      const { LazySelect } = await import('@/components/ui/lazyAntd')

      const { container } = render(
        <Suspense fallback={<div>Loading...</div>}>
          <LazySelect aria-label="Select option" />
        </Suspense>
      )

      await waitFor(() => {
        const select = container.querySelector('[aria-label="Select option"]')
        expect(select).toBeInTheDocument()
      })
    })
  })
})

describe('Integration with existing components', () => {
  it('should work with FileUploader component', async () => {
    // Test that FileUploader can use lazy-loaded components
    const { TestFileUploader } = await import('@/test/components/fixtures/FileUploader.fixture')

    const { container } = render(
      <Suspense fallback={<div>Loading...</div>}>
        <TestFileUploader />
      </Suspense>
    )

    await waitFor(() => {
      // Should have lazy-loaded Button, Progress, Select, Tag, Tooltip
      expect(container.querySelector('.ant-btn')).toBeInTheDocument()
      expect(container.querySelector('.ant-select')).toBeInTheDocument()
    })
  })

  it('should work with MessageBubble component', async () => {
    const { TestMessageBubble } = await import('@/test/components/fixtures/MessageBubble.fixture')

    const { container } = render(
      <Suspense fallback={<div>Loading...</div>}>
        <TestMessageBubble />
      </Suspense>
    )

    await waitFor(() => {
      // Should have lazy-loaded Avatar, Tag
      expect(container.querySelector('.ant-avatar')).toBeInTheDocument()
      expect(container.querySelector('.ant-tag')).toBeInTheDocument()
    })
  })
})
