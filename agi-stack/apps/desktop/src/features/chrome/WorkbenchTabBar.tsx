import type { WorkbenchTab } from './workbenchTabBarModel';

type WorkbenchTabBarProps = {
  tabs: WorkbenchTab[];
  activeTabKey: string;
  onActivate: (tab: WorkbenchTab) => void;
  onClose: (tab: WorkbenchTab) => void;
};

/** Conversations are selected from the sidebar; the shell slot stays compatible. */
export function WorkbenchTabBar(_props: WorkbenchTabBarProps) {
  return null;
}
