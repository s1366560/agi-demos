import { describe, it, expect, vi } from 'vitest'

// Mock lazyAntd before importing
vi.mock('@/components/ui/lazyAntd', () => ({
  LazyAvatar: ({ children }: any) => <div data-testid="avatar">{children}</div>,
  LazyTag: ({ children }: any) => <span data-testid="tag">{children}</span>,
}))

// Mock react-markdown
vi.mock('react-markdown', () => ({
  default: ({ children }: any) => <div data-testid="markdown">{children}</div>,
}))

vi.mock('remark-gfm', () => ({
  default: () => ({}),
}))

// Mock react-syntax-highlighter
vi.mock('react-syntax-highlighter', () => ({
  Prism: ({ children }: any) => <div data-testid="syntax-highlighter">{children}</div>,
}))

vi.mock('react-syntax-highlighter/dist/esm/styles/prism', () => ({
  vscDarkPlus: {},
}))

describe('Debug Import Test', () => {
  it('should import debug MessageBubble', async () => {
    const module = await import('../../../components/agent/messageBubble/debug')
    console.log('Debug module keys:', Object.keys(module))
    console.log('Debug MessageBubble:', module.MessageBubble)
    expect(module.MessageBubble).toBeDefined()
  })

  it('should import debug2 MessageBubble (with react-markdown)', async () => {
    const module = await import('../../../components/agent/messageBubble/debug2')
    console.log('Debug2 module keys:', Object.keys(module))
    console.log('Debug2 MessageBubble:', module.MessageBubble)
    expect(module.MessageBubble).toBeDefined()
  })

  it('should import debug3 MessageBubble (with dynamic imports)', async () => {
    const module = await import('../../../components/agent/messageBubble/debug3')
    console.log('Debug3 module keys:', Object.keys(module))
    console.log('Debug3 MessageBubble:', module.MessageBubble)
    expect(module.MessageBubble).toBeDefined()
  })

  it('should import debug4 MessageBubble (with types import)', async () => {
    const module = await import('../../../components/agent/messageBubble/debug4')
    console.log('Debug4 module keys:', Object.keys(module))
    console.log('Debug4 MessageBubble:', module.MessageBubble)
    expect(module.MessageBubble).toBeDefined()
  })

  it('should import debug5 MessageBubble (with marker symbols)', async () => {
    const module = await import('../../../components/agent/messageBubble/debug5')
    console.log('Debug5 module keys:', Object.keys(module))
    console.log('Debug5 MessageBubble:', module.MessageBubble)
    expect(module.MessageBubble).toBeDefined()
  })

  it('should import debug6 MessageBubble (copy of index.tsx)', async () => {
    const module = await import('../../../components/agent/messageBubble/debug6')
    console.log('Debug6 module keys:', Object.keys(module))
    console.log('Debug6 MessageBubble:', module.MessageBubble)
    expect(module.MessageBubble).toBeDefined()
  })
})
