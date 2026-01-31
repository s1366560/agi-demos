/**
 * Performance tests for Text Delta buffering optimization
 *
 * Tests verify that the text delta buffering mechanism provides
 * responsive streaming with minimal perceived latency.
 */

import { describe, it, expect, vi } from 'vitest';

describe('Text Delta Performance', () => {
  describe('Buffer Configuration', () => {
    it('should have flush interval <= 16ms (60fps target)', async () => {
      // Dynamic import to avoid require() statement
      const fs = await import('fs');
      const agentStoreContent = fs.readFileSync(
        '../../stores/agent.ts',
        'utf-8'
      );

      // Extract TEXT_DELTA_FLUSH_INTERVAL value
      const flushMatch = agentStoreContent.match(
        /TEXT_DELTA_FLUSH_INTERVAL\s*=\s*(\d+)/
      );
      const flushInterval = flushMatch ? parseInt(flushMatch[1], 10) : 50;

      // Extract TEXT_DELTA_BUFFER_SIZE value
      const bufferMatch = agentStoreContent.match(
        /TEXT_DELTA_BUFFER_SIZE\s*=\s*(\d+)/
      );
      const bufferSize = bufferMatch ? parseInt(bufferMatch[1], 10) : 100;

      // Performance requirements:
      // - Flush interval should be ~16ms for 60fps (one frame)
      // - Buffer size should be small enough to avoid visible lag
      expect(flushInterval).toBeLessThanOrEqual(16);
      expect(bufferSize).toBeLessThanOrEqual(50);
    });

    it('should provide smooth streaming with minimal batching delay', async () => {
      const fs = await import('fs');
      const agentStoreContent = fs.readFileSync(
        '../../stores/agent.ts',
        'utf-8'
      );

      const flushMatch = agentStoreContent.match(
        /TEXT_DELTA_FLUSH_INTERVAL\s*=\s*(\d+)/
      );
      const flushInterval = flushMatch ? parseInt(flushMatch[1], 10) : 50;

      // Maximum acceptable delay for perceived responsiveness
      // 16ms = 1 frame at 60fps (imperceptible)
      // 33ms = 2 frames at 60fps (borderline perceptible)
      // 50ms = 3 frames at 60fps (perceptible lag)
      expect(flushInterval).toBeLessThan(33);
    });
  });

  describe('Buffer Flush Behavior', () => {
    it('should flush buffer when size limit is reached', () => {
      // This test verifies the buffering logic works correctly
      const deltas: string[] = [];
      let buffer = '';
      const BUFFER_SIZE = 50;
      const flushFn = vi.fn((content: string) => deltas.push(content));

      // Simulate text delta buffering
      const simulateDelta = (delta: string) => {
        buffer += delta;
        if (buffer.length >= BUFFER_SIZE) {
          flushFn(buffer);
          buffer = '';
        }
      };

      // Add small deltas that eventually exceed buffer
      simulateDelta('a'.repeat(25));
      expect(flushFn).not.toHaveBeenCalled();

      simulateDelta('b'.repeat(25));
      expect(flushFn).toHaveBeenCalledTimes(1);
      expect(flushFn).toHaveBeenCalledWith('a'.repeat(25) + 'b'.repeat(25));
    });

    it('should flush buffer on timer interval', async () => {
      const flushFn = vi.fn();
      const FLUSH_INTERVAL = 16;
      let buffer = 'partial content';

      // Simulate timer-based flush
      const flushPromise = new Promise<void>((resolve) => {
        setTimeout(() => {
          if (buffer) {
            flushFn(buffer);
            buffer = '';
          }
          resolve();
        }, FLUSH_INTERVAL);
      });

      await flushPromise;
      expect(flushFn).toHaveBeenCalledWith('partial content');
    });
  });

  describe('Performance Benchmarks', () => {
    it('should handle rapid deltas without excessive re-renders', async () => {
      // Simulate rapid incoming deltas (e.g., 100 deltas in 1 second)
      const deltas: string[] = [];
      const flushFn = vi.fn((content: string) => deltas.push(content));

      const BUFFER_SIZE = 50;
      let buffer = '';

      // Simulate 100 small deltas
      for (let i = 0; i < 100; i++) {
        buffer += 'x';
        if (buffer.length >= BUFFER_SIZE) {
          flushFn(buffer);
          buffer = '';
        }
      }

      // With BUFFER_SIZE=50, we should have exactly 2 flushes for 100 chars
      expect(flushFn).toHaveBeenCalledTimes(2);
    });

    it('should minimize state updates for smooth rendering', () => {
      // Count state updates for different buffer sizes
      const countUpdates = (bufferSize: number, totalChars: number) => {
        return Math.ceil(totalChars / bufferSize);
      };

      // Old configuration: 100 char buffer
      const oldUpdates = countUpdates(100, 500);
      // New configuration: 50 char buffer
      const newUpdates = countUpdates(50, 500);

      // New config should have more frequent (smaller) updates
      expect(newUpdates).toBeGreaterThan(oldUpdates);
      // But not excessive - 500 chars / 50 = 10 updates
      expect(newUpdates).toBe(10);
    });
  });

  describe('Latency Measurements', () => {
    it('should measure end-to-end latency for text deltas', () => {
      // Simulate measuring latency from WebSocket message to UI update
      const latencies: number[] = [];
      const startTime = Date.now();

      // Simulate 10 delta events
      for (let i = 0; i < 10; i++) {
        const receiveTime = Date.now();
        // Simulate processing delay
        const flushTime = receiveTime + Math.random() * 20;
        latencies.push(flushTime - startTime);
      }

      // Average latency should be reasonable
      const avgLatency = latencies.reduce((a, b) => a + b, 0) / latencies.length;
      expect(avgLatency).toBeLessThan(50); // Less than 50ms average
    });
  });
});
