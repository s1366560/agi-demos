import { describe, it, expect } from 'vitest'

describe('Types Import Test', () => {
  it('should import types', async () => {
    const types = await import('../../../components/agent/messageBubble/types')
    console.log('Types keys:', Object.keys(types))
    expect(types).toBeDefined()
  })
})
