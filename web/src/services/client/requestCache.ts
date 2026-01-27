/**
 * Request Cache Layer
 *
 * Provides a simple in-memory cache for GET requests with TTL-based expiration.
 *
 * Features:
 * - Cache key generation based on URL and params
 * - Configurable TTL (time-to-live) per entry
 * - Cache statistics (hits, misses, size)
 * - Global enable/disable flag
 * - Manual cache clearing and invalidation
 */

/**
 * Cache entry structure
 */
interface CacheEntry<T> {
  data: T;
  expiresAt: number;
}

/**
 * Cache statistics
 */
export interface CacheStats {
  hits: number;
  misses: number;
  size: number;
}

/**
 * Request cache implementation
 */
class RequestCacheImpl {
  private cache: Map<string, CacheEntry<unknown>> = new Map();
  private _hits: number = 0;
  private _misses: number = 0;
  private _defaultTTL: number = 60000; // 60 seconds default

  /**
   * Enable/disable caching globally
   */
  enabled: boolean = true;

  /**
   * Get the default TTL in milliseconds
   */
  get defaultTTL(): number {
    return this._defaultTTL;
  }

  /**
   * Set the default TTL in milliseconds
   */
  set defaultTTL(value: number) {
    this._defaultTTL = value;
  }

  /**
   * Generate a cache key from URL and params
   */
  generateCacheKey(url: string, params?: Record<string, unknown> | null): string {
    if (!params || Object.keys(params).length === 0) {
      return url;
    }
    // Sort keys to ensure consistent ordering
    const sortedParams = Object.keys(params).sort();
    const paramString = sortedParams
      .map((key) => `${key}=${JSON.stringify(params[key])}`)
      .join('&');
    return `${url}?${paramString}`;
  }

  /**
   * Get a value from cache
   */
  get<T>(key: string): T | undefined {
    if (!this.enabled) {
      return undefined;
    }

    const entry = this.cache.get(key);
    if (!entry) {
      this._misses++;
      return undefined;
    }

    // Check if entry has expired
    if (Date.now() > entry.expiresAt) {
      this.cache.delete(key);
      this._misses++;
      return undefined;
    }

    this._hits++;
    return entry.data as T;
  }

  /**
   * Set a value in cache with optional TTL
   */
  set<T>(key: string, data: T, ttl?: number): void {
    if (!this.enabled) {
      return;
    }

    const actualTTL = ttl ?? this._defaultTTL;
    this.cache.set(key, {
      data,
      expiresAt: Date.now() + actualTTL,
    });
  }

  /**
   * Delete a specific entry from cache
   */
  delete(key: string): void {
    this.cache.delete(key);
  }

  /**
   * Clear all cached entries
   */
  clear(): void {
    this.cache.clear();
    this._hits = 0;
    this._misses = 0;
  }

  /**
   * Get cache statistics
   */
  getStats(): CacheStats {
    return {
      hits: this._hits,
      misses: this._misses,
      size: this.cache.size,
    };
  }

  /**
   * Check if cache has an entry (regardless of expiration)
   */
  has(key: string): boolean {
    return this.cache.has(key);
  }

  /**
   * Get all cache keys
   */
  keys(): string[] {
    return Array.from(this.cache.keys());
  }
}

// Export singleton instance
export const requestCache = new RequestCacheImpl();

// Export type for convenience
export type { CacheEntry, CacheStats };
