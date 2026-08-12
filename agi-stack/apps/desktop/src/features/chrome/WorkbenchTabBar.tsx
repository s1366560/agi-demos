import { Cross2Icon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { tabKey, type WorkbenchTab, type WorkbenchTabViewSection } from './workbenchTabBarModel';
import './WorkbenchTabBar.css';

const VIEW_TAB_LABEL_KEYS: Record<WorkbenchTabViewSection, string> = {
  workspace: 'workspaceTree.workspaces',
  home: 'nav.home',
  board: 'nav.myWork',
  automations: 'nav.automations',
  search: 'nav.search',
  activity: 'sidebar.activity',
};

type WorkbenchTabBarProps = {
  tabs: WorkbenchTab[];
  activeTabKey: string;
  onActivate: (tab: WorkbenchTab) => void;
  onClose: (tab: WorkbenchTab) => void;
};

/**
 * Orca-style tab row above the workbench: one tab per open view plus one per
 * open conversation. Deliberately simpler than orca — no keep-alive, no
 * split panes; activation just routes through the existing section and
 * conversation selection.
 */
export function WorkbenchTabBar({
  tabs,
  activeTabKey,
  onActivate,
  onClose,
}: WorkbenchTabBarProps) {
  const { t } = useI18n();

  const tabLabel = (tab: WorkbenchTab): string =>
    tab.kind === 'view'
      ? t(VIEW_TAB_LABEL_KEYS[tab.section])
      : tab.title || t('session.untitled');

  return (
    <div className="workbench-tab-bar" role="toolbar" aria-label={t('tabs.bar')}>
      {tabs.map((tab) => {
        const key = tabKey(tab);
        const active = key === activeTabKey;
        const label = tabLabel(tab);
        return (
          <div
            key={key}
            className={`workbench-tab ${active ? 'active' : ''}`}
            data-tab-kind={tab.kind}
          >
            <button
              type="button"
              className="workbench-tab-activate"
              aria-pressed={active}
              title={label}
              onClick={() => onActivate(tab)}
            >
              <span>{label}</span>
            </button>
            <button
              type="button"
              className="workbench-tab-close"
              aria-label={t('tabs.close')}
              title={t('tabs.close')}
              onClick={() => onClose(tab)}
            >
              <Cross2Icon />
            </button>
          </div>
        );
      })}
    </div>
  );
}
