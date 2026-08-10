import type { ChromeApi } from './chrome-api';

declare global {
  /**
   * MV3 `chrome` global, narrowed to the structural surface this extension
   * actually uses (see src/chrome-api.ts). WXT does not ship @types/chrome,
   * so the global is declared here instead of relying on `any`.
   */
  const chrome: ChromeApi;
}

export {};
