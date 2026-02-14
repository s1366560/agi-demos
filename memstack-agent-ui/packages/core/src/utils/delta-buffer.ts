/**
 * memstack-agent-ui - Delta Buffering Utilities
 *
 * Batching utilities for high-frequency streaming events.
 * Reduces re-renders and improves performance during streaming.
 *
 * @packageDocumentation
 */

/**
 * Token delta buffer state
 *
 * Tracks accumulated text/thought deltas and flush timing
 */
export interface DeltaBufferState {
  /** Accumulated text delta content */
  textDeltaBuffer: string;

  /** Timer for flushing text deltas */
  textDeltaFlushTimer: ReturnType<typeof setTimeout> | null;

  /** Accumulated thought delta content */
  thoughtDeltaBuffer: string;

  /** Timer for flushing thought deltas */
  thoughtDeltaFlushTimer: ReturnType<typeof setTimeout> | null;

  /** Accumulated act delta content */
  actDeltaBuffer: Record<string, string> | null;

  /** Timer for flushing act deltas */
  actDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
}

/**
 * Default batching intervals (milliseconds)
 *
 * - TEXT_DELTA_BATCH_MS: 50ms for smooth text streaming
 * - THOUGHT_DELTA_BATCH_MS: 50ms for thought updates
 * - ACT_DELTA_BATCH_MS: 100ms for tool argument streaming
 */
export const DEFAULT_BATCH_INTERVALS = {
  TEXT_DELTA_BATCH_MS: 50,
  THOUGHT_DELTA_BATCH_MS: 50,
  ACT_DELTA_BATCH_MS: 100,
} as const;

/**
 * Delta buffer manager
 *
 * Manages per-conversation delta buffers with automatic flushing.
 */
export class DeltaBufferManager {
  private buffers: Map<string, DeltaBufferState>;
  private batchIntervals: typeof DEFAULT_BATCH_INTERVALS;

  constructor(
    batchIntervals: Partial<typeof DEFAULT_BATCH_INTERVALS> = {}
  ) {
    this.buffers = new Map();
    this.batchIntervals = { ...DEFAULT_BATCH_INTERVALS, ...batchIntervals };
  }

  /**
   * Get or create delta buffer for a conversation
   *
   * @param conversationId - Conversation ID
   * @returns Delta buffer state
   */
  getBuffer(conversationId: string): DeltaBufferState {
    let buffer = this.buffers.get(conversationId);
    if (!buffer) {
      buffer = this.createBuffer();
      this.buffers.set(conversationId, buffer);
    }
    return buffer;
  }

  /**
   * Create a new empty buffer state
   *
   * @returns Fresh buffer state
   */
  private createBuffer(): DeltaBufferState {
    return {
      textDeltaBuffer: '',
      textDeltaFlushTimer: null,
      thoughtDeltaBuffer: '',
      thoughtDeltaFlushTimer: null,
      actDeltaBuffer: null,
      actDeltaFlushTimer: null,
    };
  }

  /**
   * Clear delta buffers for a conversation
   *
   * Cancels pending timers and resets buffer state.
   * IMPORTANT: Call before starting new streaming to prevent stale content.
   *
   * @param conversationId - Conversation ID
   */
  clearBuffer(conversationId: string): void {
    const buffer = this.buffers.get(conversationId);
    if (!buffer) return;

    // Clear timers
    if (buffer.textDeltaFlushTimer) {
      clearTimeout(buffer.textDeltaFlushTimer);
      buffer.textDeltaFlushTimer = null;
    }
    if (buffer.thoughtDeltaFlushTimer) {
      clearTimeout(buffer.thoughtDeltaFlushTimer);
      buffer.thoughtDeltaFlushTimer = null;
    }
    if (buffer.actDeltaFlushTimer) {
      clearTimeout(buffer.actDeltaFlushTimer);
      buffer.actDeltaFlushTimer = null;
    }

    // Reset buffer state
    buffer.textDeltaBuffer = '';
    buffer.thoughtDeltaBuffer = '';
    buffer.actDeltaBuffer = null;
  }

  /**
   * Clear all buffers
   *
   * Used when switching conversations or on cleanup.
   */
  clearAllBuffers(): void {
    for (const [conversationId] of this.buffers.keys()) {
      this.clearBuffer(conversationId);
    }
    this.buffers.clear();
  }

  /**
   * Add text delta to buffer with auto-flush
   *
   * @param conversationId - Conversation ID
   * @param delta - Text delta to add
   * @param onFlush - Callback when buffer flushes
   * @returns Flush timer ID (for cancellation if needed)
   */
  addTextDelta(
    conversationId: string,
    delta: string,
    onFlush: (content: string) => void
  ): ReturnType<typeof setTimeout> | null {
    const buffer = this.getBuffer(conversationId);
    buffer.textDeltaBuffer += delta;

    // Schedule flush if not already scheduled
    if (!buffer.textDeltaFlushTimer) {
      buffer.textDeltaFlushTimer = setTimeout(() => {
        const content = buffer.textDeltaBuffer;
        buffer.textDeltaBuffer = '';
        buffer.textDeltaFlushTimer = null;
        onFlush(content);
      }, this.batchIntervals.TEXT_DELTA_BATCH_MS);
    }

    return buffer.textDeltaFlushTimer;
  }

  /**
   * Add thought delta to buffer with auto-flush
   *
   * @param conversationId - Conversation ID
   * @param delta - Thought delta to add
   * @param onFlush - Callback when buffer flushes
   * @returns Flush timer ID (for cancellation if needed)
   */
  addThoughtDelta(
    conversationId: string,
    delta: string,
    onFlush: (content: string) => void
  ): ReturnType<typeof setTimeout> | null {
    const buffer = this.getBuffer(conversationId);
    buffer.thoughtDeltaBuffer += delta;

    // Schedule flush if not already scheduled
    if (!buffer.thoughtDeltaFlushTimer) {
      buffer.thoughtDeltaFlushTimer = setTimeout(() => {
        const content = buffer.thoughtDeltaBuffer;
        buffer.thoughtDeltaBuffer = '';
        buffer.thoughtDeltaFlushTimer = null;
        onFlush(content);
      }, this.batchIntervals.THOUGHT_DELTA_BATCH_MS);
    }

    return buffer.thoughtDeltaFlushTimer;
  }

  /**
   * Add act delta to buffer with auto-flush
   *
   * Act deltas are keyed by tool_call_id.
   *
   * @param conversationId - Conversation ID
   * @param toolCallId - Tool call ID
   * @param delta - Act delta to add
   * @param onFlush - Callback when buffer flushes
   * @returns Flush timer ID (for cancellation if needed)
   */
  addActDelta(
    conversationId: string,
    toolCallId: string,
    delta: string,
    onFlush: (content: Record<string, string>) => void
  ): ReturnType<typeof setTimeout> | null {
    const buffer = this.getBuffer(conversationId);

    // Initialize act buffer if needed
    if (!buffer.actDeltaBuffer) {
      buffer.actDeltaBuffer = {};
    }
    if (!buffer.actDeltaBuffer[toolCallId]) {
      buffer.actDeltaBuffer[toolCallId] = '';
    }
    buffer.actDeltaBuffer[toolCallId] += delta;

    // Schedule flush if not already scheduled
    if (!buffer.actDeltaFlushTimer) {
      buffer.actDeltaFlushTimer = setTimeout(() => {
        const content = buffer.actDeltaBuffer || {};
        buffer.actDeltaBuffer = null;
        buffer.actDeltaFlushTimer = null;
        onFlush(content);
      }, this.batchIntervals.ACT_DELTA_BATCH_MS);
    }

    return buffer.actDeltaFlushTimer;
  }

  /**
   * Manually flush all pending buffers for a conversation
   *
   * Use this to force immediate flush before state changes.
   *
   * @param conversationId - Conversation ID
   * @param onTextFlush - Text flush callback
   * @param onThoughtFlush - Thought flush callback
   * @param onActFlush - Act flush callback
   */
  flush(
    conversationId: string,
    onTextFlush: (content: string) => void,
    onThoughtFlush: (content: string) => void,
    onActFlush: (content: Record<string, string>) => void
  ): void {
    const buffer = this.buffers.get(conversationId);
    if (!buffer) return;

    // Flush text
    if (buffer.textDeltaBuffer) {
      onTextFlush(buffer.textDeltaBuffer);
      buffer.textDeltaBuffer = '';
      if (buffer.textDeltaFlushTimer) {
        clearTimeout(buffer.textDeltaFlushTimer);
        buffer.textDeltaFlushTimer = null;
      }
    }

    // Flush thought
    if (buffer.thoughtDeltaBuffer) {
      onThoughtFlush(buffer.thoughtDeltaBuffer);
      buffer.thoughtDeltaBuffer = '';
      if (buffer.thoughtDeltaFlushTimer) {
        clearTimeout(buffer.thoughtDeltaFlushTimer);
        buffer.thoughtDeltaFlushTimer = null;
      }
    }

    // Flush act
    if (buffer.actDeltaBuffer) {
      onActFlush(buffer.actDeltaBuffer);
      buffer.actDeltaBuffer = null;
      if (buffer.actDeltaFlushTimer) {
        clearTimeout(buffer.actDeltaFlushTimer);
        buffer.actDeltaFlushTimer = null;
      }
    }
  }

  /**
   * Remove buffer for a conversation
   *
   * Call when conversation is deleted.
   *
   * @param conversationId - Conversation ID
   */
  remove(conversationId: string): void {
    this.clearBuffer(conversationId);
    this.buffers.delete(conversationId);
  }

  /**
   * Get buffer for direct access (advanced use)
   *
   * Allows direct manipulation of buffer state.
   * Use with caution - may bypass flush logic.
   *
   * @param conversationId - Conversation ID
   * @returns Buffer state or undefined
   */
  peek(conversationId: string): DeltaBufferState | undefined {
    return this.buffers.get(conversationId);
  }
}

/**
 * Create a singleton delta buffer manager
 *
 * Global instance for app-wide delta buffering.
 */
let globalDeltaManager: DeltaBufferManager | null = null;

export function getDeltaManager(): DeltaBufferManager {
  if (!globalDeltaManager) {
    globalDeltaManager = new DeltaBufferManager();
  }
  return globalDeltaManager;
}

/**
 * Reset global delta manager
 *
 * Clears all buffers. Use between test runs.
 */
export function resetDeltaManager(): void {
  if (globalDeltaManager) {
    globalDeltaManager.clearAllBuffers();
  }
  globalDeltaManager = null;
}
