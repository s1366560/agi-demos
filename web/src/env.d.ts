/// <reference types="vite/client" />

/**
 * Environment variables type definitions for MemStack Web
 */

interface ImportMetaEnv {
  /** API host (e.g., localhost:8000) */
  readonly VITE_API_HOST?: string | undefined;
  /** API base path (default: /api/v1) */
  readonly VITE_API_BASE_PATH?: string | undefined;
  /** WebSocket host (if different from API host) */
  readonly VITE_WS_HOST?: string | undefined;
  /** Sandbox service host */
  readonly VITE_SANDBOX_HOST?: string | undefined;
  /** Development mode flag */
  readonly DEV: boolean;
  /** Production mode flag */
  readonly PROD: boolean;
  /** Base URL */
  readonly BASE_URL: string;
  /** Mode */
  readonly MODE: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
