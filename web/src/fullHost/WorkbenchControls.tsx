import { TenantHeaderView, type TenantHeaderProps } from '../components/layout/TenantHeaderView';
import {
  TenantSidebarView,
  type TenantChatSidebarProps,
} from '../components/layout/TenantSidebarView';
import {
  CommandPaletteView,
  type CommandPaletteProps,
} from '../components/common/CommandPaletteView';
import { useHeaderItems } from './navigation';
import { useSignedSidebar } from './sidebarData';

export function FullHeader(props: TenantHeaderProps) {
  return <TenantHeaderView {...props} useNavigationItems={useHeaderItems} />;
}

const NoLegacyNavigationSlot = () => null;
export function FullSidebar(props: TenantChatSidebarProps) {
  return (
    <TenantSidebarView
      {...props}
      useSidebarData={useSignedSidebar}
      useNavigationItems={useHeaderItems}
      NavigationSlot={NoLegacyNavigationSlot}
    />
  );
}

export function FullPalette(props: CommandPaletteProps) {
  const items = useHeaderItems();
  const { canCreate, conversations, navigation } = useSignedSidebar();
  return (
    <CommandPaletteView
      {...props}
      navigationItems={items}
      agentWorkspaceEnabled={canCreate}
      rowLink={navigation?.link}
      conversations={conversations}
    />
  );
}
