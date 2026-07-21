import { useCallback, useEffect, useRef, useState } from 'react';
import type React from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { AlertTriangle, Info, Lightbulb, Wrench } from 'lucide-react';

import { MaintenanceOperation } from '../../components/maintenance/MaintenanceOperation';
import { graphService } from '../../services/graphService';
import { confirmAction } from '../../utils/confirmAction';
import { logger } from '../../utils/logger';

import type { EmbeddingStatus, GraphStats, MaintenanceStatus } from '../../services/graphService';

const formatStat = (value: number | undefined): string =>
  value === undefined ? '-' : value.toLocaleString();

export const Maintenance: React.FC = () => {
  const { t } = useTranslation();
  const { tenantId, projectId } = useParams();
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [refreshLoading, setRefreshLoading] = useState(false);
  const [dedupProcessing, setDedupProcessing] = useState(false);
  const [cleanProcessing, setCleanProcessing] = useState(false);
  const [rebuildLoading, setRebuildLoading] = useState(false);
  const [embeddingLoading, setEmbeddingLoading] = useState(false);
  const [embeddingStatus, setEmbeddingStatus] = useState<EmbeddingStatus | null>(null);
  const [maintenanceStatus, setMaintenanceStatus] = useState<MaintenanceStatus | null>(null);
  const [initialLoadError, setInitialLoadError] = useState<string | null>(null);
  const [initialLoadRetryToken, setInitialLoadRetryToken] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [messageType, setMessageType] = useState<'info' | 'error'>('info');
  const activeProjectIdRef = useRef<string | undefined>(projectId);
  activeProjectIdRef.current = projectId;

  const isActiveProject = useCallback(
    (requestProjectId: string) => activeProjectIdRef.current === requestProjectId,
    []
  );

  const refreshMaintenanceStatus = useCallback(
    async (requestProjectId: string) => {
      try {
        const nextStatus = await graphService.getMaintenanceStatus(requestProjectId);
        if (isActiveProject(requestProjectId)) {
          setMaintenanceStatus(nextStatus);
        }
      } catch (error) {
        if (isActiveProject(requestProjectId)) {
          logger.error('Failed to refresh maintenance status', error);
        }
      }
    },
    [isActiveProject]
  );

  useEffect(() => {
    setRefreshLoading(false);
    setDedupProcessing(false);
    setCleanProcessing(false);
    setRebuildLoading(false);
    setEmbeddingLoading(false);
    setMessage(null);
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;

    let isCurrent = true;
    const reportInitialLoadError = (error: unknown) => {
      logger.error('Failed to load maintenance data', error);
      if (isCurrent) {
        setInitialLoadError(t('project.maintenance.messages.initial_load_failed'));
      }
    };

    setInitialLoadError(null);
    setStats(null);
    setEmbeddingStatus(null);
    setMaintenanceStatus(null);
    void graphService
      .getGraphStats(tenantId, projectId)
      .then((nextStats) => {
        if (isCurrent) setStats(nextStats);
      })
      .catch(reportInitialLoadError);
    void graphService
      .getEmbeddingStatus(projectId)
      .then((nextStatus) => {
        if (isCurrent) setEmbeddingStatus(nextStatus);
      })
      .catch(reportInitialLoadError);
    void graphService
      .getMaintenanceStatus(projectId)
      .then((nextStatus) => {
        if (isCurrent) setMaintenanceStatus(nextStatus);
      })
      .catch(reportInitialLoadError);

    return () => {
      isCurrent = false;
    };
  }, [tenantId, projectId, t, initialLoadRetryToken]);

  const handleRefresh = async () => {
    const requestProjectId = projectId;
    if (!requestProjectId) return;
    setRefreshLoading(true);
    try {
      const res = await graphService.incrementalRefresh({ project_id: requestProjectId });
      if (!isActiveProject(requestProjectId)) return;

      // Handle both numeric and string responses for episodes_to_process
      const episodesValue: unknown = res.episodes_to_process;
      const count = typeof episodesValue === 'number' ? episodesValue : 0;
      // If the response contains a descriptive message, use it directly
      if (typeof episodesValue === 'string' && Number.isNaN(Number(episodesValue))) {
        setMessage(t('project.maintenance.messages.refreshed_text', { text: episodesValue }));
      } else {
        setMessage(t('project.maintenance.messages.refreshed', { count }));
      }
      setMessageType('info');
    } catch (e) {
      if (!isActiveProject(requestProjectId)) return;
      logger.error('Failed to refresh graph', e);
      setMessage(t('project.maintenance.messages.refresh_failed'));
      setMessageType('error');
    } finally {
      if (isActiveProject(requestProjectId)) {
        setRefreshLoading(false);
      }
    }
  };

  const handleDedupCheck = async () => {
    const requestProjectId = projectId;
    if (!requestProjectId) return;
    try {
      const res = await graphService.deduplicateEntities({
        dry_run: true,
        project_id: requestProjectId,
      });
      if (!isActiveProject(requestProjectId)) return;

      const count = res.duplicates_found ?? 0;
      setMessage(t('project.maintenance.messages.duplicates_found', { count }));
      setMessageType('info');
    } catch (e) {
      if (!isActiveProject(requestProjectId)) return;
      logger.error('Failed to check duplicate entities', e);
      setMessage(t('project.maintenance.messages.dedup_failed'));
      setMessageType('error');
    }
  };

  const handleDedupMerge = async () => {
    const requestProjectId = projectId;
    if (!requestProjectId) return;
    if (
      !(await confirmAction({
        title: t('project.maintenance.confirm.dedup_merge'),
        danger: true,
      }))
    ) {
      return;
    }
    setDedupProcessing(true);
    try {
      const res = await graphService.deduplicateEntities({
        dry_run: false,
        project_id: requestProjectId,
      });
      if (!isActiveProject(requestProjectId)) return;

      if (res.task_id) {
        setMessage(t('project.maintenance.messages.dedup_started', { taskId: res.task_id }));
      } else if (res.message) {
        setMessage(res.message);
      } else {
        setMessage(t('project.maintenance.messages.merge_complete'));
      }
      setMessageType('info');
      void refreshMaintenanceStatus(requestProjectId);
    } catch (e) {
      if (!isActiveProject(requestProjectId)) return;
      logger.error('Failed to merge duplicate entities', e);
      setMessage(t('project.maintenance.messages.dedup_merge_failed'));
      setMessageType('error');
    } finally {
      if (isActiveProject(requestProjectId)) {
        setDedupProcessing(false);
      }
    }
  };

  const handleCleanCheck = async () => {
    const requestProjectId = projectId;
    if (!requestProjectId) return;
    try {
      const res = await graphService.invalidateStaleEdges({
        dry_run: true,
        project_id: requestProjectId,
      });
      if (!isActiveProject(requestProjectId)) return;

      const count = res.stale_edges_found ?? 0;
      setMessage(t('project.maintenance.messages.stale_edges_found', { count }));
      setMessageType('info');
    } catch (e) {
      if (!isActiveProject(requestProjectId)) return;
      logger.error('Failed to check stale edges', e);
      setMessage(t('project.maintenance.messages.clean_failed'));
      setMessageType('error');
    }
  };

  const handleClean = async () => {
    const requestProjectId = projectId;
    if (!requestProjectId) return;
    if (
      !(await confirmAction({
        title: t('project.maintenance.confirm.clean_stale'),
        danger: true,
      }))
    ) {
      return;
    }
    setCleanProcessing(true);
    try {
      const res = await graphService.invalidateStaleEdges({
        dry_run: false,
        project_id: requestProjectId,
      });
      if (!isActiveProject(requestProjectId)) return;

      const count = res.deleted ?? 0;
      setMessage(t('project.maintenance.messages.stale_edges_deleted', { count }));
      setMessageType('info');
      void refreshMaintenanceStatus(requestProjectId);
    } catch (e) {
      if (!isActiveProject(requestProjectId)) return;
      logger.error('Failed to clean stale edges', e);
      setMessage(t('project.maintenance.messages.clean_failed'));
      setMessageType('error');
    } finally {
      if (isActiveProject(requestProjectId)) {
        setCleanProcessing(false);
      }
    }
  };

  const handleRebuild = async () => {
    const requestProjectId = projectId;
    if (!requestProjectId) return;
    if (
      !(await confirmAction({
        title: t('project.maintenance.confirm.rebuild'),
        danger: true,
      }))
    ) {
      return;
    }
    setRebuildLoading(true);
    try {
      const res = await graphService.rebuildCommunities(true, requestProjectId);
      if (!isActiveProject(requestProjectId)) return;

      if (res.task_id) {
        setMessage(t('project.maintenance.messages.rebuild_started', { taskId: res.task_id }));
      } else {
        const responseMessage: unknown = res.message;
        setMessage(
          typeof responseMessage === 'string' && responseMessage.trim()
            ? responseMessage
            : res.status
        );
      }
      setMessageType('info');
    } catch (e) {
      if (!isActiveProject(requestProjectId)) return;
      logger.error('Failed to rebuild communities', e);
      setMessage(t('project.maintenance.messages.rebuild_failed'));
      setMessageType('error');
    } finally {
      if (isActiveProject(requestProjectId)) {
        setRebuildLoading(false);
      }
    }
  };

  const handleExport = async () => {
    const requestProjectId = projectId;
    if (!requestProjectId) return;
    try {
      const data = await graphService.exportData({
        tenant_id: tenantId,
        project_id: requestProjectId,
      });
      if (!isActiveProject(requestProjectId)) return;

      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `graph-export-${String(Date.now())}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      setMessage(t('project.maintenance.messages.export_success'));
      setMessageType('info');
    } catch (e) {
      if (!isActiveProject(requestProjectId)) return;
      logger.error('Failed to export graph data', e);
      setMessage(t('project.maintenance.messages.export_failed'));
      setMessageType('error');
    }
  };

  const handleRebuildEmbeddings = async () => {
    const requestProjectId = projectId;
    if (!requestProjectId) return;
    if (
      !(await confirmAction({
        title: t('project.maintenance.confirm.rebuild_embeddings'),
        danger: true,
      }))
    ) {
      return;
    }
    setEmbeddingLoading(true);
    try {
      const res = await graphService.rebuildEmbeddings(requestProjectId);
      if (!isActiveProject(requestProjectId)) return;

      setMessage(t('project.maintenance.messages.embedding_rebuilt', { count: res.result.nodes }));
      setMessageType('info');
      // Refresh embedding status after rebuild
      const newStatus = await graphService.getEmbeddingStatus(requestProjectId);
      if (isActiveProject(requestProjectId)) {
        setEmbeddingStatus(newStatus);
      }
    } catch (e) {
      if (!isActiveProject(requestProjectId)) return;
      logger.error('Failed to rebuild embeddings', e);
      setMessage(t('project.maintenance.messages.embedding_failed'));
      setMessageType('error');
    } finally {
      if (isActiveProject(requestProjectId)) {
        setEmbeddingLoading(false);
      }
    }
  };

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-8 p-4 sm:p-6 md:p-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          {t('project.maintenance.title')}
        </h1>
        <p className="text-slate-500 dark:text-slate-400 mt-1">
          {t('project.maintenance.subtitle')}
        </p>
        {initialLoadError && (
          <div
            role="alert"
            className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-red-50 p-4 text-red-700 dark:bg-red-900/20 dark:text-red-300"
          >
            <span>{initialLoadError}</span>
            <button
              type="button"
              onClick={() => {
                setInitialLoadRetryToken((token) => token + 1);
              }}
              className="rounded-md border border-red-200 px-3 py-1 text-sm font-medium text-red-700 transition-colors hover:bg-red-100 focus-visible:ring-2 focus-visible:ring-red-400 focus-visible:outline-none dark:border-red-800 dark:text-red-300 dark:hover:bg-red-900/40"
            >
              {t('project.maintenance.messages.retry')}
            </button>
          </div>
        )}
        {message && (
          <div
            role={messageType === 'error' ? 'alert' : 'status'}
            className={`mt-4 p-4 rounded-lg ${
              messageType === 'error'
                ? 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-300'
                : 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300'
            }`}
          >
            {message}
          </div>
        )}
      </div>

      {/* Graph Stats */}
      <section aria-labelledby="graph-statistics-heading" className="flex flex-col gap-4">
        <h2
          id="graph-statistics-heading"
          className="text-lg font-semibold text-slate-900 dark:text-white"
        >
          {t('project.maintenance.stats.title')}
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-white dark:bg-surface-dark p-4 rounded-lg border border-slate-200 dark:border-slate-800 shadow-sm text-center">
            <p className="text-3xl font-bold text-slate-900 tabular-nums dark:text-white">
              {formatStat(stats?.entity_count)}
            </p>
            <p className="text-xs text-slate-500 uppercase tracking-wider mt-1">
              {t('project.maintenance.stats.entities')}
            </p>
          </div>
          <div className="bg-white dark:bg-surface-dark p-4 rounded-lg border border-slate-200 dark:border-slate-800 shadow-sm text-center">
            <p className="text-3xl font-bold text-slate-900 tabular-nums dark:text-white">
              {formatStat(stats?.episodic_count)}
            </p>
            <p className="text-xs text-slate-500 uppercase tracking-wider mt-1">
              {t('project.maintenance.stats.episodes')}
            </p>
          </div>
          <div className="bg-white dark:bg-surface-dark p-4 rounded-lg border border-slate-200 dark:border-slate-800 shadow-sm text-center">
            <p className="text-3xl font-bold text-slate-900 tabular-nums dark:text-white">
              {formatStat(stats?.community_count)}
            </p>
            <p className="text-xs text-slate-500 uppercase tracking-wider mt-1">
              {t('project.maintenance.stats.communities')}
            </p>
          </div>
          <div className="bg-white dark:bg-surface-dark p-4 rounded-lg border border-slate-200 dark:border-slate-800 shadow-sm text-center">
            <p className="text-3xl font-bold text-slate-900 tabular-nums dark:text-white">
              {formatStat(stats?.edge_count)}
            </p>
            <p className="text-xs text-slate-500 uppercase tracking-wider mt-1">
              {t('project.maintenance.stats.relationships')}
            </p>
          </div>
        </div>
      </section>

      {/* Operations */}
      <div className="bg-white dark:bg-surface-dark rounded-lg shadow-sm border border-slate-200 dark:border-slate-800 overflow-hidden">
        <div className="p-6 border-b border-slate-200 dark:border-slate-800">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2">
            <Wrench size={16} className="text-primary" />
            {t('project.maintenance.ops.title')}
          </h2>
        </div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          <MaintenanceOperation
            title={t('project.maintenance.ops.refresh.title')}
            description={t('project.maintenance.ops.refresh.desc')}
            icon="refresh"
            actionLabel={
              refreshLoading
                ? t('project.maintenance.ops.refresh.loading')
                : t('project.maintenance.ops.refresh.button')
            }
            onAction={() => {
              void handleRefresh();
            }}
            loading={refreshLoading}
          />
          <MaintenanceOperation
            title={t('project.maintenance.ops.dedup.title')}
            description={t('project.maintenance.ops.dedup.desc')}
            icon="content_copy"
            actionLabel={
              dedupProcessing
                ? t('project.maintenance.ops.dedup.processing')
                : t('project.maintenance.ops.dedup.merge')
            }
            secondaryActionLabel={t('project.maintenance.ops.dedup.check')}
            onAction={() => {
              void handleDedupMerge();
            }}
            onSecondaryAction={() => {
              void handleDedupCheck();
            }}
            loading={dedupProcessing}
            warning
          />
          <MaintenanceOperation
            title={t('project.maintenance.ops.clean.title')}
            description={t('project.maintenance.ops.clean.desc')}
            icon="cleaning_services"
            actionLabel={
              cleanProcessing
                ? t('project.maintenance.ops.clean.cleaning')
                : t('project.maintenance.ops.clean.clean')
            }
            secondaryActionLabel={t('project.maintenance.ops.clean.check')}
            onAction={() => {
              void handleClean();
            }}
            onSecondaryAction={() => {
              void handleCleanCheck();
            }}
            loading={cleanProcessing}
            warning
          />
          <MaintenanceOperation
            title={t('project.maintenance.ops.rebuild.title')}
            description={t('project.maintenance.ops.rebuild.desc')}
            icon="group_work"
            actionLabel={
              rebuildLoading
                ? t('project.maintenance.ops.rebuild.rebuilding')
                : t('project.maintenance.ops.rebuild.button')
            }
            onAction={() => {
              void handleRebuild();
            }}
            loading={rebuildLoading}
          />
          <MaintenanceOperation
            title={t('project.maintenance.ops.export.title')}
            description={t('project.maintenance.ops.export.desc')}
            icon="download"
            actionLabel={t('project.maintenance.ops.export.button')}
            onAction={() => {
              void handleExport();
            }}
          />
          {/* Embedding Management */}
          {embeddingStatus && (
            <MaintenanceOperation
              title={t('project.maintenance.ops.embedding.title')}
              description={
                <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                  <span>
                    {t('project.maintenance.ops.embedding.provider_dimension', {
                      provider: embeddingStatus.current_provider,
                      dimension: embeddingStatus.current_dimension,
                    })}
                  </span>
                  {!embeddingStatus.is_compatible ? (
                    <span className="px-2 py-0.5 bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 text-xs rounded-full">
                      {t('project.maintenance.ops.embedding.dimension_mismatch')}
                    </span>
                  ) : embeddingStatus.missing_embeddings > 0 ? (
                    <span className="px-2 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 text-xs rounded-full">
                      {t('project.maintenance.ops.embedding.missing_vectors', {
                        count: embeddingStatus.missing_embeddings,
                      })}
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 text-xs rounded-full">
                      {t('project.maintenance.ops.embedding.status_ok')}
                    </span>
                  )}
                </div>
              }
              icon="model_training"
              actionLabel={
                embeddingLoading
                  ? t('project.maintenance.ops.embedding.rebuilding')
                  : t('project.maintenance.ops.embedding.button')
              }
              onAction={() => {
                void handleRebuildEmbeddings();
              }}
              loading={embeddingLoading}
              warning={!embeddingStatus.is_compatible}
            />
          )}
        </div>
      </div>

      {/* Recommendations */}
      <div className="bg-indigo-50 dark:bg-indigo-900/20 rounded-lg border border-indigo-200 dark:border-indigo-800 p-6">
        <h2 className="text-lg font-semibold text-indigo-900 dark:text-indigo-300 mb-4 flex items-center gap-2">
          <Lightbulb size={16} />
          {t('project.maintenance.recommendations.title')}
        </h2>
        <div className="space-y-3">
          {(maintenanceStatus?.recommendations ?? []).length > 0 ? (
            (maintenanceStatus?.recommendations ?? []).map((recommendation, index) => (
              <div
                key={`${recommendation.type}-${String(index)}`}
                className="flex items-start gap-3 p-3 bg-white dark:bg-surface-dark rounded-lg border border-indigo-100 dark:border-indigo-800/50 shadow-sm"
              >
                <AlertTriangle size={16} className="text-yellow-500 mt-0.5" />
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-slate-900 dark:text-white">
                      {recommendation.type.replaceAll('_', ' ')}
                    </p>
                    <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-2xs font-semibold uppercase text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300">
                      {t(`project.maintenance.recommendations.priority.${recommendation.priority}`)}
                    </span>
                  </div>
                  <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">
                    {recommendation.message}
                  </p>
                </div>
              </div>
            ))
          ) : (
            <div className="flex items-center gap-3 p-3 bg-white dark:bg-surface-dark rounded-lg border border-indigo-100 dark:border-indigo-800/50 shadow-sm">
              <Info size={16} className="text-indigo-500" />
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {t('project.maintenance.recommendations.none')}
              </p>
            </div>
          )}
        </div>
      </div>

      <div className="bg-yellow-50 dark:bg-yellow-900/20 rounded-lg border border-yellow-200 dark:border-yellow-800 p-6">
        <h2 className="text-lg font-semibold text-yellow-800 dark:text-yellow-300 mb-2 flex items-center gap-2">
          <Info size={16} />
          {t('project.maintenance.warning.title')}
        </h2>
        <p className="text-yellow-700 dark:text-yellow-400 text-sm">
          {t('project.maintenance.warning.desc')}
        </p>
      </div>
    </div>
  );
};
