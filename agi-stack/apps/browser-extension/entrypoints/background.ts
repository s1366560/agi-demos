import { defineBackground } from 'wxt/utils/define-background';
import type { ChromeApi } from '../src/chrome-api';
import { createBridge } from '../src/handlers';
import { startNativeTransport } from '../src/transport';

export default defineBackground(() => {
  const api = chrome as unknown as ChromeApi;
  const bridge = createBridge(api);
  startNativeTransport(api, bridge);
});
