import { defineBackground } from 'wxt/utils/define-background';
import type { ChromeApi } from '../src/chrome-api';
import { createBridge } from '../src/handlers';
import { createSidePanelChat } from '../src/sidepanel-chat';
import { startNativeTransport } from '../src/transport';

export default defineBackground(() => {
  const api = chrome as unknown as ChromeApi;
  // Chromium's version token is protocol metadata, not a content/intent classifier.
  const browserFamily = navigator.userAgent.split(' ').some(token => token.startsWith('Edg/'))
    ? 'edge'
    : 'chrome';
  // Keep one bridge per worker: its hello persists profile identity before
  // publication and retains this worker's instance identity across reconnects.
  const bridge = createBridge(api, browserFamily);
  const transport = startNativeTransport(api, bridge);
  createSidePanelChat({ chrome: api, transport });
  // Clicking the toolbar action opens the side panel chat.
  void api.sidePanel?.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {
    /* older Chrome without the sidePanel API */
  });
});
