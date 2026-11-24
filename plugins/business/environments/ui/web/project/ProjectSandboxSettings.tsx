import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { message as antdMessage } from 'antd';
import { RefreshCw, Power, RotateCcw, Server } from 'lucide-react';
import { formatDateTime } from '../../../../../../sdk/memstack-plugin-sdk/ui/localDate';
import { confirmAction } from '../../../../../../sdk/memstack-plugin-sdk/ui/confirmAction';
import {
  SettingsSection,
  secondaryButtonClass,
} from '../../../../../../sdk/memstack-plugin-sdk/ui/SettingsSection';
interface SandboxView {
  sandbox_id: string | null;
  status: string;
  last_accessed_at?: string | null | undefined;
}
interface SandboxSettingsProps {
  projectId: string;
  client: {
    getProjectSandbox(projectId: string): Promise<SandboxView | null>;
    getStats(
      projectId: string
    ): Promise<{ cpu_percent?: number; memory_used_mb?: number; memory_limit_mb?: number }>;
    restartSandbox(projectId: string): Promise<unknown>;
    terminateSandbox(projectId: string): Promise<unknown>;
  };
  actions?: (refresh: () => Promise<void>) => React.ReactNode;
}
export const ProjectSandboxSettings: React.FC<SandboxSettingsProps> = ({
  projectId,
  client,
  actions,
}) => {
  const { t } = useTranslation();
  const [sandboxInfo, setSandboxInfo] = useState<SandboxView | null>(null);
  const [stats, setStats] = useState<{
    cpu_percent?: number;
    memory_used_mb?: number;
    memory_limit_mb?: number;
  } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);

  const fetchSandboxInfo = useCallback(async () => {
    try {
      setLoading(true);
      setLoadError(null);
      const info = await client.getProjectSandbox(projectId);
      setSandboxInfo(info);
      // Only fetch stats if sandbox is running
      if (info?.status === 'running') {
        try {
          const statsData = await client.getStats(projectId);
          setStats(statsData);
        } catch {
          setStats(null);
        }
      } else {
        setStats(null);
      }
    } catch (cause) {
      setLoadError(cause instanceof Error ? cause.message : String(cause));
      setSandboxInfo(null);
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, [projectId, client]);

  useEffect(() => {
    void fetchSandboxInfo();
  }, [fetchSandboxInfo]);

  const handleRestart = useCallback(async () => {
    setActionLoading(true);
    try {
      await client.restartSandbox(projectId);
      void antdMessage.success(t('project.settings.sandboxRestartSuccess', 'Sandbox restarted'));
      await fetchSandboxInfo();
    } catch {
      void antdMessage.error(t('project.settings.sandboxActionFailed', 'Sandbox action failed'));
    } finally {
      setActionLoading(false);
    }
  }, [projectId, client, fetchSandboxInfo, t]);

  const handleTerminate = useCallback(async () => {
    if (
      !(await confirmAction({
        title: t('project.settings.sandboxTerminateConfirm', 'Terminate sandbox?'),
        content: t(
          'project.settings.sandboxTerminateConfirmDesc',
          'This stops the running sandbox environment. Unsaved work inside it may be lost.'
        ),
        danger: true,
      }))
    ) {
      return;
    }
    setActionLoading(true);
    try {
      await client.terminateSandbox(projectId);
      void antdMessage.success(t('project.settings.sandboxTerminateSuccess', 'Sandbox terminated'));
      await fetchSandboxInfo();
    } catch {
      void antdMessage.error(t('project.settings.sandboxActionFailed', 'Sandbox action failed'));
    } finally {
      setActionLoading(false);
    }
  }, [projectId, client, fetchSandboxInfo, t]);

  const statusColor =
    sandboxInfo?.status === 'running'
      ? 'text-green-600 dark:text-green-400'
      : sandboxInfo?.status === 'terminated'
        ? 'text-content-tertiary'
        : sandboxInfo?.status === 'error'
          ? 'text-red-600 dark:text-red-400'
          : 'text-yellow-600 dark:text-yellow-400';

  return (
    <SettingsSection
      id="sandbox"
      icon={<Server className="h-4 w-4" />}
      title={t('project.settings.sandboxSectionTitle')}
    >
      {loading ? (
        <div className="text-sm text-gray-400">{t('project.settings.sandboxLoading')}</div>
      ) : loadError ? (
        <div role="alert">
          {loadError}{' '}
          <button className={secondaryButtonClass} onClick={() => void fetchSandboxInfo()}>
            {t('common.retry')}
          </button>
        </div>
      ) : !sandboxInfo ? (
        <div className="text-sm text-gray-500 dark:text-slate-400">
          {t('project.settings.sandboxEmpty')}
        </div>
      ) : (
        <div className="space-y-4">
          {/* Status Row */}
          <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
            <div className="rounded border border-gray-200 bg-gray-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900/70">
              <span className="block text-xs text-gray-500 dark:text-slate-400">
                {t('project.settings.sandboxStatusLabel')}:
              </span>
              <span className={`font-medium ${statusColor}`}>{sandboxInfo.status}</span>
            </div>
            <div className="rounded border border-gray-200 bg-gray-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900/70">
              <span className="block text-xs text-gray-500 dark:text-slate-400">
                {t('project.settings.sandboxIdLabel')}:
              </span>
              <span className="break-all font-mono text-xs text-gray-600 dark:text-slate-300">
                {sandboxInfo.sandbox_id ? sandboxInfo.sandbox_id.slice(0, 12) + '…' : '-'}
              </span>
            </div>
          </div>

          {/* Last Accessed */}
          {sandboxInfo.last_accessed_at && (
            <div className="text-sm">
              <span className="text-gray-500 dark:text-slate-400">
                {t('project.settings.sandboxLastAccessed')}:
              </span>{' '}
              <span className="text-gray-700 dark:text-slate-300">
                {formatDateTime(sandboxInfo.last_accessed_at)}
              </span>
            </div>
          )}

          {/* Resource Stats (only when running) */}
          {stats && (
            <div className="grid grid-cols-1 gap-3 rounded border border-gray-200 bg-gray-50 p-3 text-sm dark:border-slate-800 dark:bg-slate-900/70 sm:grid-cols-2">
              <div>
                <span className="text-gray-500 dark:text-slate-400">
                  {t('project.settings.sandboxCpuLabel')}:
                </span>{' '}
                <span className="text-gray-700 dark:text-slate-300">
                  {stats.cpu_percent?.toFixed(1) ?? '-'}%
                </span>
              </div>
              <div>
                <span className="text-gray-500 dark:text-slate-400">
                  {t('project.settings.sandboxMemoryLabel')}:
                </span>{' '}
                <span className="text-gray-700 dark:text-slate-300">
                  {stats.memory_used_mb?.toFixed(0) ?? '-'} /{' '}
                  {stats.memory_limit_mb?.toFixed(0) ?? '-'} MB
                </span>
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex flex-wrap gap-2 pt-2">
            <button
              type="button"
              onClick={() => {
                void handleRestart();
              }}
              disabled={actionLoading || sandboxInfo.status === 'terminated'}
              className={`${secondaryButtonClass} flex-1 sm:flex-none`}
            >
              <RotateCcw className="h-4 w-4" />
              {t('project.settings.sandboxRestart')}
            </button>
            <button
              type="button"
              onClick={() => {
                void handleTerminate();
              }}
              disabled={actionLoading || sandboxInfo.status === 'terminated'}
              className="inline-flex min-h-9 flex-1 items-center justify-center gap-2 rounded border border-red-200 bg-white px-3 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-900/70 dark:bg-slate-950 dark:text-red-400 dark:hover:bg-red-950/30 sm:flex-none"
            >
              <Power className="h-4 w-4" />
              {t('project.settings.sandboxTerminate')}
            </button>
            <button
              type="button"
              onClick={() => {
                void fetchSandboxInfo();
              }}
              disabled={actionLoading}
              className={`${secondaryButtonClass} flex-1 sm:flex-none`}
            >
              <RefreshCw className="h-4 w-4" />
              {t('common.refresh')}
            </button>
          </div>
        </div>
      )}
      {actions?.(fetchSandboxInfo)}
    </SettingsSection>
  );
};
ProjectSandboxSettings.displayName = 'ProjectSettings.Sandbox';
