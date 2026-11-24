import { useConversationsStore } from '@business/agent/ui/web/stores/agent/conversationsStore';
import {
  useWebCommandNavigationItemsV2,
  useWebFeatureEnabledV2,
} from '@/routes/v2/webFeatureAuthorityV2';
import { CommandPaletteView, type CommandPaletteProps } from './CommandPaletteView';

export type { CommandPaletteProps } from './CommandPaletteView';
export function CommandPalette(props: CommandPaletteProps) {
  const conversations = useConversationsStore((s) => s.conversations);
  const navigationItems = useWebCommandNavigationItemsV2('tenant', {
    tenantId: props.tenantId,
    projectId: props.projectId,
  });
  const agentWorkspaceEnabled = useWebFeatureEnabledV2('tenant-agent-workspace', 'command');
  return (
    <CommandPaletteView
      {...props}
      conversations={conversations}
      navigationItems={navigationItems}
      agentWorkspaceEnabled={agentWorkspaceEnabled}
    />
  );
}
export default CommandPalette;
