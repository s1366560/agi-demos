import type { ComponentProps } from 'react';

import { ChatPanel } from '../features/chat/ChatPanel';
import { PlatformPluginConversationSlots } from '../features/chat/PlatformPluginConversationSlots';

export type DesktopConversationInputV2 = Readonly<ComponentProps<typeof ChatPanel>>;

export interface DesktopConversationSurfacePropsV2 {
  readonly input: DesktopConversationInputV2;
}

export function DesktopConversationSurfaceV2({ input }: DesktopConversationSurfacePropsV2) {
  return (
    <>
      <ChatPanel {...input} />
      <PlatformPluginConversationSlots active />
    </>
  );
}
