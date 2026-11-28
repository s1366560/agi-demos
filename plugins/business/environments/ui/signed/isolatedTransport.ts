// The isolated workbench supplies its release-bound channel factory to the original viewers.
export const getAuthToken = (): null => null;
export function createWebSocketUrl(): never {
  throw new Error('sandbox_channel_required');
}
export const createWebSocketAuthProtocols = createWebSocketUrl;
export const buildDesktopWebSocketProtocols = createWebSocketUrl;
