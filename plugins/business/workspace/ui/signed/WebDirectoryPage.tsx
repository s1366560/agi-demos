import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createMemoryRouter, RouterProvider, Link } from 'react-router-dom';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { ConfigProvider, theme } from 'antd';
import { darkTheme, lightTheme } from '../../../../../web/src/theme/antdTheme';
import { SkeletonLoader } from '../../../../../web/src/components/common/SkeletonLoader';
import { useHostAppearance } from './useHostAppearance';
import { WorkspaceListView } from '../web/tenant/WorkspaceListView';
import { resolveWorkspaceSummary } from '../web/tenant/resolveWorkspaceSummary';
import type {
  Workspace,
  CyberObjective,
  WorkspacePlanSnapshot,
  WorkspaceTask,
} from '../web/types/workspace';
import { projectDirectory } from './createWorkspace';
import { readDirectory } from './readDirectory';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import './workspaceDirectory.css';

async function mount() {
  const host = window.memstack;
  const scope = await host.getContext();
  const base = projectDirectory(scope.tenantId, scope.projectId);
  const chinese = scope.locale.startsWith('zh');
  const i18n = createInstance();
  await i18n.init({
    lng: chinese ? 'zh' : 'en',
    resources: { en: { translation: en }, zh: { translation: zh } },
    interpolation: { escapeValue: false },
  });
  const summary = async (_tenant: string, _project: string, id: string) => {
    try {
      const sources = (await host.invoke('list-directory', { summary_for: id })) as {
        objectives: CyberObjective[] | null;
        plan: WorkspacePlanSnapshot | null;
        tasks: WorkspaceTask[] | null;
      };
      return resolveWorkspaceSummary(sources.objectives, sources.plan, async () => sources.tasks);
    } catch {
      return resolveWorkspaceSummary(null, null, async () => null);
    }
  };
  const relativeTime = new Intl.RelativeTimeFormat(scope.locale, { numeric: 'auto' });
  const formatDistance = (input: string) => {
    const minutes = Math.trunc((Date.parse(input) - Date.now()) / 60000);
    return Math.abs(minutes) < 60
      ? relativeTime.format(minutes, 'minute')
      : Math.abs(minutes) < 1440
        ? relativeTime.format(Math.trunc(minutes / 60), 'hour')
        : relativeTime.format(Math.trunc(minutes / 1440), 'day');
  };
  function Directory() {
    const dark = useHostAppearance() === 'dark';
    const [rows, setRows] = useState<Workspace[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const request = useRef<AbortController | null>(null);
    useEffect(() => () => request.current?.abort(), []);
    const load = useCallback(async () => {
      request.current?.abort();
      const current = new AbortController();
      request.current = current;
      setLoading(true);
      try {
        const workspaces = await readDirectory(host, current.signal);
        if (!current.signal.aborted) {
          setRows(workspaces);
          setError(null);
        }
      } catch (cause) {
        if (!current.signal.aborted) setError(String(cause));
      } finally {
        if (!current.signal.aborted) setLoading(false);
      }
    }, []);
    return (
      <ConfigProvider theme={dark ? { ...darkTheme, algorithm: theme.darkAlgorithm } : lightTheme}>
        <WorkspaceListView
          tenantId={scope.tenantId}
          projectId={scope.projectId}
          workspaces={rows}
          isLoading={loading}
          workspaceError={error}
          loadWorkspaces={load}
          workspacePath={(id) => base + '/' + encodeURIComponent(id)}
          loadWorkspaceSummary={summary}
          formatDistanceToNow={formatDistance}
          loadingView={<SkeletonLoader type="card" count={6} />}
          extraActions={<Link to={base + '/export'}>{chinese ? '导出 CSV' : 'Export CSV'}</Link>}
        />
      </ConfigProvider>
    );
  }
  const router = createMemoryRouter([{ path: '*', element: <Directory /> }], {
    initialEntries: [scope.pathname + scope.search],
  });
  let last = scope.pathname + scope.search;
  router.subscribe(({ location, historyAction }) => {
    const next = location.pathname + location.search;
    if (next !== last) {
      last = next;
      void host.navigate(next, { replace: historyAction === 'REPLACE' });
    }
  });
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={i18n}>
      <RouterProvider router={router} />
    </I18nextProvider>
  );
}
void mount();
