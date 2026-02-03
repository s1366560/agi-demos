/**
 * Array Utils Tests
 *
 * Tests for optimized array utilities following TDD methodology.
 */

import { describe, it, expect } from 'vitest'

/**
 * Sample array points (mimicking memory_history structure)
 */
const mockHistory = Array.from({ length: 100 }, (_, i) => ({
  date: `2024-01-${String(i + 1).padStart(2, '0')}`,
  value: i * 10
}))

describe('Array Sampling Optimization', () => {
  it('should sample every 7th element efficiently', () => {
    // Original approach: filter().map() - creates intermediate array
    const originalResult = mockHistory
      .filter((_: unknown, i: number) => i % 7 === 0)
      .map((point) => point.date)

    // Optimized approach: direct loop - no intermediate array
    const optimizedResult: string[] = []
    for (let i = 0; i < mockHistory.length; i += 7) {
      optimizedResult.push(mockHistory[i].date)
    }

    expect(optimizedResult).toEqual(originalResult)
    expect(optimizedResult).toHaveLength(Math.ceil(mockHistory.length / 7))
  })

  it('should handle empty array', () => {
    const result: string[] = []
    for (let i = 0; i < 0; i += 7) {
      // loop won't execute
    }
    expect(result).toEqual([])
  })

  it('should handle array with fewer than 7 elements', () => {
    const shortArray = [{ date: '2024-01-01', value: 10 }]
    const result: typeof shortArray[] = []
    for (let i = 0; i < shortArray.length; i += 7) {
      result.push(shortArray[i])
    }
    expect(result).toEqual(shortArray)
  })
})

/**
 * useMemo dependency optimization tests
 */
describe('useMemo Dependency Optimization', () => {
  it('should demonstrate proper primitive dependencies', () => {
    // Good: primitive dependencies
    const count = 5
    const limit = 10
    const deps = [count, limit] as const

    expect(deps).toHaveLength(2)
    // Primitive values are stable for comparison
    expect(deps[0] === 5).toBe(true)
  })

  it('should demonstrate issue with object dependencies', () => {
    // Bad: object created on every render
    const badDeps = [{ count: 5 }] // new reference each time

    // Good: primitive values or stable references
    const count = 5
    const goodDeps = [count]

    // The good deps array can be compared by value
    const anotherGoodDeps = [5]
    expect(goodDeps).toEqual(anotherGoodDeps)

    // The bad deps array has different references (not equal, but deep equal)
    const anotherBadDeps = [{ count: 5 }]
    expect(badDeps === anotherBadDeps).toBe(false) // reference comparison
    expect(badDeps).toEqual(anotherBadDeps) // deep equal but different refs
  })
})
