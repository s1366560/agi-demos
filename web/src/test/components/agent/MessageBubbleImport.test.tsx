/**
 * Simple import test for MessageBubble
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock dependencies first
vi.mock('react-markdown', () => ({
  default: ({ children }: any) => <div data-testid="markdown">{children}</div>,
}))

vi.mock('remark-gfm', () => ({
  default: () => ({}),
}))

vi.mock('react-syntax-highlighter', () => ({
  Prism: ({ children }: any) => <div data-testid="syntax-highlighter">{children}</div>,
}))

vi.mock('react-syntax-highlighter/dist/esm/styles/prism', () => ({
  vscDarkPlus: {},
}))

// Mock lazy antd - use same path as in code (@/components/ui/lazyAntd)
vi.mock('@/components/ui/lazyAntd', () => ({
  LazyAvatar: ({ children, className }: any) => (
    <div data-testid="avatar" className={className}>
      {children}
    </div>
  ),
  LazyTag: ({ children, className }: any) => (
    <span data-testid="tag" className={className}>
      {children}
    </span>
  ),
}))

import React from 'react'

describe('MessageBubble Import Test', () => {
  it('should import the legacy module', async () => {
    const module = await import('../../../components/agent/MessageBubble.legacy')
    console.log('Legacy module keys:', Object.keys(module))
    console.log('Legacy MessageBubble:', module.MessageBubble)
    expect(module).toBeDefined()
  })

  it('should import the module', async () => {
    const module = await import('../../../components/agent/messageBubble')
    console.log('Module keys:', Object.keys(module))
    console.log('MessageBubble:', module.MessageBubble)
    console.log('MessageBubble type:', typeof module.MessageBubble)
    console.log('UserMessage:', module.UserMessage)
    console.log('AssistantMessage:', module.AssistantMessage)
    expect(module).toBeDefined()
  })

  it('should import individual components', async () => {
    const module = await import('../../../components/agent/messageBubble')
    console.log('UserMessage type:', typeof module.UserMessage)
    console.log('AssistantMessage type:', typeof module.AssistantMessage)
    expect(module.UserMessage).toBeDefined()
    expect(module.AssistantMessage).toBeDefined()
  })

  it('should import MessageBubble', async () => {
    const { MessageBubble } = await import('../../../components/agent/messageBubble')
    console.log('MessageBubble direct:', MessageBubble)
    console.log('MessageBubble.User:', MessageBubble?.User)
    expect(MessageBubble).toBeDefined()
  })
})
