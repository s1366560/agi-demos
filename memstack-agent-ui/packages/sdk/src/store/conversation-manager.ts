/**
 * memstack-agent-ui - Conversation Manager
 *
 * Multi-conversation management with LRU caching and IndexedDB persistence.
 *
 * @packageDocumentation
 */

import type {
  ConversationState,
  createDefaultConversationState,
} from '../../core/src/types/conversation-state';

/**
 * LRU Cache configuration
 */
export interface LRUCacheOptions {
  /** Maximum number of conversations to cache in memory (default: 10) */
  maxSize?: number;

  /** Maximum age of cached conversations in milliseconds (default: 30 minutes) */
  maxAge?: number;
}

/**
 * LRU Cache entry
 */
interface LRUCacheEntry {
  /** Conversation state */
  state: ConversationState;

  /** Timestamp when entry was last accessed */
  lastAccess: number;

  /** Timestamp when entry was created */
  createdAt: number;
}

/**
 * LRU Cache for conversation state
 *
 * Manages in-memory conversation state with size limits and age-based eviction.
 * Older or least-recently-used conversations are evicted first.
 */
export class LRUCache {
  private cache: Map<string, LRUCacheEntry>;
  private maxSize: number;
  private maxAge: number;

  constructor(options: LRUCacheOptions = {}) {
    this.cache = new Map();
    this.maxSize = options.maxSize ?? 10;
    this.maxAge = options.maxAge ?? 30 * 60 * 1000; // 30 minutes default
  }

  /**
   * Get conversation state from cache
   *
   * Updates last access time for LRU tracking.
   *
   * @param conversationId - Conversation ID to retrieve
   * @returns Conversation state or undefined if not in cache
   */
  get(conversationId: string): ConversationState | undefined {
    const entry = this.cache.get(conversationId);
    if (entry) {
      entry.lastAccess = Date.now();
      return entry.state;
    }
    return undefined;
  }

  /**
   * Set conversation state in cache
   *
   * Evicts oldest entry if at max size.
   *
   * @param conversationId - Conversation ID to set
   * @param state - Conversation state to cache
   */
  set(conversationId: string, state: ConversationState): void {
    const now = Date.now();

    // Check if we need to evict
    if (!this.cache.has(conversationId) && this.cache.size >= this.maxSize) {
      this.evictOldest();
    }

    this.cache.set(conversationId, {
      state,
      lastAccess: now,
      createdAt: now,
    });
  }

  /**
   * Check if conversation is in cache
   *
   * @param conversationId - Conversation ID to check
   * @returns true if conversation is cached
   */
  has(conversationId: string): boolean {
    return this.cache.has(conversationId);
  }

  /**
   * Remove conversation from cache
   *
   * @param conversationId - Conversation ID to remove
   * @returns true if conversation was in cache
   */
  delete(conversationId: string): boolean {
    return this.cache.delete(conversationId);
  }

  /**
   * Clear all cached conversations
   */
  clear(): void {
    this.cache.clear();
  }

  /**
   * Get all cached conversation IDs
   *
   * @returns Array of conversation IDs in cache
   */
  keys(): string[] {
    return Array.from(this.cache.keys());
  }

  /**
   * Get size of cache
   *
   * @returns Number of conversations in cache
   */
  get size(): number {
    return this.cache.size;
  }

  /**
   * Evict oldest (least-recently-used) entry
   *
   * Finds entry with oldest lastAccess time and removes it.
   */
  private evictOldest(): void {
    let oldestKey: string | null = null;
    let oldestAccess = Infinity;

    for (const [key, entry] of this.cache.entries()) {
      if (entry.lastAccess < oldestAccess) {
        oldestAccess = entry.lastAccess;
        oldestKey = key;
      }
    }

    if (oldestKey) {
      this.cache.delete(oldestKey);

      // Persist to IndexedDB before eviction
      this.persistToIndexedDB(oldestKey, this.cache.get(oldestKey)!.state);
    }
  }

  /**
   * Evict stale entries based on age
   *
   * Removes entries older than maxAge.
   */
  evictStale(): void {
    const now = Date.now();
    const staleKeys: string[] = [];

    for (const [key, entry] of this.cache.entries()) {
      if (now - entry.createdAt > this.maxAge) {
        staleKeys.push(key);
      }
    }

    for (const key of staleKeys) {
      const entry = this.cache.get(key)!;
      this.cache.delete(key);
      this.persistToIndexedDB(key, entry.state);
    }
  }

  /**
   * Persist conversation to IndexedDB (async)
   *
   * @param conversationId - Conversation ID
   * @param state - Conversation state to persist
   */
  private persistToIndexedDB(
    conversationId: string,
    state: ConversationState
  ): void {
    // IndexedDB persistence would be implemented here
    // For now, this is a placeholder for future implementation
    if (typeof indexedDB !== 'undefined') {
      // TODO: Implement IndexedDB persistence
      console.debug('[LRUCache] Would persist to IndexedDB:', conversationId);
    }
  }

  /**
   * Load conversation from IndexedDB (async)
   *
   * @param conversationId - Conversation ID to load
   * @returns Promise resolving to state or undefined
   */
  async loadFromIndexedDB(
    conversationId: string
  ): Promise<ConversationState | undefined> {
    // IndexedDB loading would be implemented here
    // For now, this is a placeholder for future implementation
    if (typeof indexedDB !== 'undefined') {
      // TODO: Implement IndexedDB loading
      console.debug('[LRUCache] Would load from IndexedDB:', conversationId);
    }
    return undefined;
  }
}

/**
 * Conversation manager options
 */
export interface ConversationManagerOptions {
  /** LRU cache options */
  cache?: LRUCacheOptions;

  /** Initial conversations to load */
  initialConversations?: Map<string, ConversationState>;
}

/**
 * Conversation manager
 *
 * Manages multiple conversations with:
 * - In-memory LRU cache
 * - IndexedDB persistence
 * - Active conversation tracking
 */
export class ConversationManager {
  private cache: LRUCache;
  private activeConversationId: string | null = null;

  constructor(options: ConversationManagerOptions = {}) {
    this.cache = new LRUCache(options.cache);

    // Load initial conversations if provided
    if (options.initialConversations) {
      for (const [id, state] of options.initialConversations) {
        this.cache.set(id, state);
      }
    }
  }

  /**
   * Get conversation state
   *
   * @param conversationId - Conversation ID
   * @returns Conversation state or creates default if not exists
   */
  get(conversationId: string): ConversationState {
    let state = this.cache.get(conversationId);

    if (!state) {
      // Try loading from IndexedDB
      state = await this.cache.loadFromIndexedDB(conversationId);
    }

    if (!state) {
      // Create default state
      state = createDefaultConversationState();
      this.cache.set(conversationId, state);
    }

    return state;
  }

  /**
   * Update conversation state
   *
   * Merges partial updates into existing conversation state.
   *
   * @param conversationId - Conversation ID
   * @param updates - Partial state updates to merge
   */
  update(
    conversationId: string,
    updates: Partial<ConversationState>
  ): void {
    const currentState = this.get(conversationId);
    const updatedState = { ...currentState, ...updates };
    this.cache.set(conversationId, updatedState);
  }

  /**
   * Create a new conversation
   *
   * @param id - Optional conversation ID (generates UUID if not provided)
   * @returns New conversation ID
   */
  create(id?: string): string {
    const conversationId = id ?? this.generateId();
    const state = createDefaultConversationState();
    this.cache.set(conversationId, state);
    return conversationId;
  }

  /**
   * Delete a conversation
   *
   * @param conversationId - Conversation ID to delete
   */
  delete(conversationId: string): void {
    this.cache.delete(conversationId);

    if (this.activeConversationId === conversationId) {
      this.activeConversationId = null;
    }
  }

  /**
   * Set active conversation
   *
   * @param conversationId - Conversation ID to activate, or null to clear
   */
  setActive(conversationId: string | null): void {
    this.activeConversationId = conversationId;
  }

  /**
   * Get active conversation ID
   *
   * @returns Active conversation ID or null
   */
  getActive(): string | null {
    return this.activeConversationId;
  }

  /**
   * Get all conversation IDs
   *
   * @returns Array of conversation IDs
   */
  getConversationIds(): string[] {
    return this.cache.keys();
  }

  /**
   * Get conversation count
   *
   * @returns Number of conversations
   */
  get count(): number {
    return this.cache.size;
  }

  /**
   * Clear all conversations
   */
  clear(): void {
    this.cache.clear();
    this.activeConversationId = null;
  }

  /**
   * Generate a unique conversation ID
   *
   * @returns Unique conversation ID
   */
  private generateId(): string {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    return `conv-${Date.now()}-${Math.random().toString(36).substring(2, 15)}`;
  }
}
