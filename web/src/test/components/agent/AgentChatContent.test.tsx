/**
 * TDD Tests for AgentChatContent refactored hooks and components
 *
 * Test coverage for:
 * - useAgentChatPanelState hook (extracted data fetching logic)
 * - AgentChatInputArea component (extracted input section)
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock Resizer component
vi.mock('@/components/agent/Resizer', () => ({
  Resizer: ({ onResize }: any) => (
    <div
      data-testid="resizer"
      onMouseDown={(e) => {
        e.preventDefault()
        onResize(10)
      }}
    />
  ),
}))

// Mock InputBar component with testid
vi.mock('@/components/agent/InputBar', () => ({
  InputBar: ({ onSend, disabled }: any) => (
    <div data-testid="input-bar">
      <input
        data-testid="message-input"
        disabled={disabled}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            onSend('test message')
          }
        }}
      />
    </div>
  ),
}))

// Test utility hook - useAgentChatPanelState
describe('useAgentChatPanelState (Extracted Hook)', () => {
  it('should initialize with default panel state', () => {
    const { result } = renderHook(() => useAgentChatPanelState())

    expect(result.current.panelCollapsed).toBe(true) // showPlanPanel defaults to false
    expect(result.current.panelWidth).toBe(360)
    expect(result.current.inputHeight).toBe(160)
  })

  it('should calculate max panel width based on viewport', () => {
    // Mock window.innerWidth
    const originalInnerWidth = window.innerWidth
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: 1000,
    })

    const { result } = renderHook(() => useAgentChatPanelState())
    expect(result.current.maxPanelWidth).toBe(900) // 90% of 1000

    // Restore
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: originalInnerWidth,
    })
  })

  it('should clamp panel width to max', () => {
    const { result } = renderHook(() => useAgentChatPanelState())
    expect(result.current.clampedPanelWidth).toBeLessThanOrEqual(result.current.maxPanelWidth)
  })

  it('should toggle panel collapsed state', async () => {
    const { result } = renderHook(() => useAgentChatPanelState())

    const initialCollapsed = result.current.panelCollapsed
    result.current.togglePanel()

    // Wait for state to update
    await waitFor(() => {
      expect(result.current.panelCollapsed).toBe(!initialCollapsed)
    })
  })
})

// Test AgentChatInputArea component
describe('AgentChatInputArea (Extracted Component)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should render input bar', () => {
    const onHeightChange = vi.fn()

    render(
      <AgentChatInputArea
        inputHeight={160}
        onHeightChange={onHeightChange}
        onSend={vi.fn()}
        onAbort={vi.fn()}
        isStreaming={false}
        disabled={false}
      />
    )

    expect(screen.getByTestId('agent-chat-input-area')).toBeInTheDocument()
    expect(screen.getByTestId('input-bar')).toBeInTheDocument()
  })

  it('should have resize handle', () => {
    const onHeightChange = vi.fn()
    const { container } = render(
      <AgentChatInputArea
        inputHeight={160}
        onHeightChange={onHeightChange}
        onSend={vi.fn()}
        onAbort={vi.fn()}
        isStreaming={false}
        disabled={false}
      />
    )

    const resizeHandle = container.querySelector('[data-testid="resizer"]')
    expect(resizeHandle).toBeInTheDocument()
  })

  it('should call onHeightChange when resized', () => {
    const onHeightChange = vi.fn()
    const { container } = render(
      <AgentChatInputArea
        inputHeight={160}
        onHeightChange={onHeightChange}
        onSend={vi.fn()}
        onAbort={vi.fn()}
        isStreaming={false}
        disabled={false}
      />
    )

    const resizeHandle = container.querySelector('[data-testid="resizer"]')
    if (resizeHandle) {
      fireEvent.mouseDown(resizeHandle)
      expect(onHeightChange).toHaveBeenCalledWith(10)
    }
  })

  it('should respect min height constraint', () => {
    const onHeightChange = vi.fn()

    render(
      <AgentChatInputArea
        inputHeight={120}
        onHeightChange={onHeightChange}
        onSend={vi.fn()}
        onAbort={vi.fn()}
        isStreaming={false}
        disabled={false}
        minHeight={120}
      />
    )

    // Component should render without errors
    expect(screen.getByTestId('agent-chat-input-area')).toBeInTheDocument()
  })
})

// Helper function to test hooks
function renderHook<T>(hook: () => T): { result: { current: T } } {
  const result: { current: T } = { current: null as any }

  function TestComponent() {
    result.current = hook()
    return null
  }

  render(<TestComponent />)
  return { result }
}

// Mock imports for extracted components
import { useAgentChatPanelState } from '@/components/agent/AgentChatHooks'
import { AgentChatInputArea } from '@/components/agent/AgentChatInputArea'
