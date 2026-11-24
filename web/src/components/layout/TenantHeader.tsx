import { useTranslation } from 'react-i18next';
import { Activity } from 'lucide-react';

import { useBackgroundStore, useRunningCount } from '@/stores/backgroundStore';
import { useCurrentWorkspace, useWorkspaces } from '@business/workspace/ui/web/stores/workspace';
import type { TopNavigationContext, NavigationRuntimeContext } from '@/config/navigation';
import { useWebTopNavigationItemsV2 } from '@/routes/v2/webNavigationAuthorityStateV2';
import { TenantHeaderView, type TenantHeaderProps } from './TenantHeaderView';

function BackgroundTasksButton() {
  const { t } = useTranslation();
  const runningCount = useRunningCount();
  const setPanel = useBackgroundStore((s) => s.setPanel);
  const backgroundTasksLabel =
    runningCount > 0
      ? t(
          'components.layout.header.backgroundTasksWithCount',
          'Background tasks, {{count}} running',
          {
            count: runningCount,
          }
        )
      : t('components.layout.header.backgroundTasks', 'Background tasks');

  return (
    <button
      type="button"
      onClick={() => {
        setPanel(true);
      }}
      className="relative p-1.5 sm:p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
      aria-label={backgroundTasksLabel}
    >
      <Activity size={18} />
      {runningCount > 0 && (
        <span className="absolute -top-0.5 -right-0.5 min-w-4 h-4 px-1 bg-primary text-white text-2xs font-bold rounded-full flex items-center justify-center">
          {runningCount}
        </span>
      )}
    </button>
  );
}

function useLegacyHeaderItems(context: TopNavigationContext, scope: NavigationRuntimeContext) {
  const current = useCurrentWorkspace();
  const workspaces = useWorkspaces();
  const matches = (w: { tenant_id: string; project_id: string }) =>
    w.tenant_id === scope.tenantId && (!scope.projectId || w.project_id === scope.projectId);
  return useWebTopNavigationItemsV2(context, {
    ...scope,
    preferredWorkspaceId:
      current && matches(current) ? current.id : (workspaces.find(matches)?.id ?? null),
  });
}

export default function TenantHeader(props: TenantHeaderProps) {
  return (
    <TenantHeaderView
      {...props}
      useNavigationItems={useLegacyHeaderItems}
      backgroundTasks={<BackgroundTasksButton />}
    />
  );
}
