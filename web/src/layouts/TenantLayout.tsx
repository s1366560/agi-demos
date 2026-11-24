import { BackgroundSubAgentPanel } from '@/components/agent/BackgroundSubAgentPanel';
import { CommandPalette } from '@/components/common/CommandPalette';
import { TenantChatSidebar } from '@/components/layout/TenantChatSidebar';
import TenantHeader from '@/components/layout/TenantHeader';
import { TenantLayoutView } from './TenantLayoutView';

export function TenantLayout() {
  return (
    <TenantLayoutView
      Sidebar={TenantChatSidebar}
      Header={TenantHeader}
      Palette={CommandPalette}
      backgroundPanel={<BackgroundSubAgentPanel />}
    />
  );
}
