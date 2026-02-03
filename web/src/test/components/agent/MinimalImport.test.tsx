import { describe, it, expect } from 'vitest'

describe('Minimal Import Test', () => {
  it('should import minimal MessageBubble', async () => {
    const module = await import('../../../components/agent/messageBubble/test')
    console.log('Minimal module keys:', Object.keys(module))
    console.log('Minimal MessageBubble:', module.MessageBubble)
    console.log('Minimal MessageBubble type:', typeof module.MessageBubble)
    expect(module.MessageBubble).toBeDefined()
  })
})
