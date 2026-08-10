import { defineBackground } from 'wxt/utils/define-background';
import type { ChromeApi } from '../src/chrome-api';
import { createBridge } from '../src/handlers';
import { createSidePanelChat } from '../src/sidepanel-chat';
import { startNativeTransport } from '../src/transport';

export default defineBackground(() => {
  const api = chrome as unknown as ChromeApi;
  const bridge = createBridge(api);
  const transport = startNativeTransport(api, bridge);
  createSidePanelChat({ chrome: api, transport });
  // Clicking the toolbar action opens the side panel chat.
  void api.sidePanel?.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {
    /* older Chrome without the sidePanel API */
  });
});
