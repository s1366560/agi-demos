import React, { useState, useEffect } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { MaintenanceOperation } from '../../components/maintenance/MaintenanceOperation';
import { graphService } from '../../services/graphService';

interface EmbeddingStatus {
  current_provider: string;
  current_dimension: number;
  existing_dimension: number | null;
  is_compatible: boolean;
  missing_embeddings: number;
}

export const Maintenance: React.FC = () => {
  const { t } = useTranslation();
  const { projectId } = useParams();
  const [stats, setStats] = useState<any>(null);
  const [refreshLoading, setRefreshLoading] = useState(false);
  const [dedupProcessing, setDedupProcessing] = useState(false);
  const [cleanProcessing, setCleanProcessing] = useState(false);
  const [rebuildLoading, setRebuildLoading] = useState(false);
  const [embeddingLoading, setEmbeddingLoading] = useState(false);
  const [embeddingStatus, setEmbeddingStatus] = useState<EmbeddingStatus | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (projectId) {
      graphService.getGraphStats(projectId).then(setStats).catch(console.error);
      graphService.getEmbeddingStatus(projectId).then(setEmbeddingStatus).catch(console.error);
    }
  }, [projectId]);

  const handleRefresh = async () => {
    if (!projectId) return;
    setRefreshLoading(true);
    try {
      const res = await graphService.incrementalRefresh({});
      // Handle both numeric and string responses for episodes_to_process
      const episodesValue = res.episodes_to_process ?? 0;
      const count = typeof episodesValue === 'number' ? episodesValue : 0;
      // If the response contains a descriptive message, use it directly
      if (typeof res.episodes_to_process === 'string' && isNaN(Number(res.episodes_to_process))) {
        setMessage(`已刷新 ${res.episodes_to_process}`);
      } else {
        setMessage(t('project.maintenance.messages.refreshed', { count }));
      }
    } catch (e) {
      console.error(e);
    } finally {
      setRefreshLoading(false);
    }
  };

  const handleDedupCheck = async () => {
    if (!projectId) return;
    try {
      const res = await graphService.deduplicateEntities({ dry_run: true });
      const count = res.duplicates_found ?? 0;
      setMessage(t('project.maintenance.messages.duplicates_found', { count }));
    } catch (e) {
      console.error(e);
    }
  };

  const handleDedupMerge = async () => {
    setDedupProcessing(true);
    setTimeout(() => { setDedupProcessing(false); }, 2000);
  };

  const handleCleanCheck = () => {
    alert(t('project.maintenance.messages.check_stale'));
  };

  const handleClean = () => {
    setCleanProcessing(true);
    setTimeout(() => { setCleanProcessing(false); }, 2000);
  };

  const handleRebuild = async () => {
    if (!projectId) return;
    setRebuildLoading(true);
    try {
      const res = await graphService.rebuildCommunities(true, projectId);
      setMessage(`Community rebuild started (Task ID: ${res.task_id})`);
    } catch (e) {
      console.error(e);
    } finally {
      setRebuildLoading(false);
    }
  };

  const handleExport = async () => {
    if (!projectId) return;
    try {
      await graphService.exportData({});
      setMessage(t('project.maintenance.messages.export_success'));
    } catch (e) {
      console.error(e);
    }
  };

  const handleRebuildEmbeddings = async () => {
    if (!projectId) return;
    setEmbeddingLoading(true);
    try {
      const res = await graphService.rebuildEmbeddings(projectId);
      setMessage(`成功重建 ${res.result.nodes} 个节点的 embeddings`);
      // Refresh embedding status after rebuild
      const newStatus = await graphService.getEmbeddingStatus(projectId);
      setEmbeddingStatus(newStatus);
    } catch (e) {
      console.error(e);
      setMessage('重建 embeddings 失败');
    } finally {
      setEmbeddingLoading(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto p-6 md:p-8 flex flex-col gap-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          {t('project.maintenance.title')}
        </h1>
        <p className="text-slate-500 dark:text-slate-400 mt-1">
          {t('project.maintenance.subtitle')}
        </p>
        {message && <div className="mt-4 p-4 bg-blue-50 text-blue-700 rounded-lg">{message}</div>}
      </div>

      {/* Graph Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-surface-dark p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm text-center">
          <p className="text-3xl font-bold text-slate-900 dark:text-white">
            {stats?.entity_count || '-'}
          </p>
          <p className="text-xs text-slate-500 uppercase tracking-wider mt-1">
            {t('project.maintenance.stats.entities')}
          </p>
        </div>
        <div className="bg-white dark:bg-surface-dark p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm text-center">
          <p className="text-3xl font-bold text-slate-900 dark:text-white">
            {stats?.episodic_count || '-'}
          </p>
          <p className="text-xs text-slate-500 uppercase tracking-wider mt-1">
            {t('project.maintenance.stats.episodes')}
          </p>
        </div>
        <div className="bg-white dark:bg-surface-dark p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm text-center">
          <p className="text-3xl font-bold text-slate-900 dark:text-white">
            {stats?.community_count || '-'}
          </p>
          <p className="text-xs text-slate-500 uppercase tracking-wider mt-1">
            {t('project.maintenance.stats.communities')}
          </p>
        </div>
        <div className="bg-white dark:bg-surface-dark p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm text-center">
          <p className="text-3xl font-bold text-slate-900 dark:text-white">
            {stats?.edge_count || '-'}
          </p>
          <p className="text-xs text-slate-500 uppercase tracking-wider mt-1">
            {t('project.maintenance.stats.relationships')}
          </p>
        </div>
      </div>

      {/* Operations */}
      <div className="bg-white dark:bg-surface-dark rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 overflow-hidden">
        <div className="p-6 border-b border-slate-200 dark:border-slate-800">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2">
            <span className="material-symbols-outlined text-primary">build</span>
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
            onAction={handleRefresh}
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
            onAction={handleDedupMerge}
            onSecondaryAction={handleDedupCheck}
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
            onAction={handleClean}
            onSecondaryAction={handleCleanCheck}
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
            onAction={handleRebuild}
            loading={rebuildLoading}
          />
          <MaintenanceOperation
            title={t('project.maintenance.ops.export.title')}
            description={t('project.maintenance.ops.export.desc')}
            icon="download"
            actionLabel={t('project.maintenance.ops.export.button')}
            onAction={handleExport}
          />
          {/* Embedding Management */}
          {embeddingStatus && (
            <MaintenanceOperation
              title={t('project.maintenance.ops.embedding.title')}
              description={
                <div className="flex items-center gap-3">
                  <span>
                    {embeddingStatus.current_provider} ({embeddingStatus.current_dimension}维)
                  </span>
                  {!embeddingStatus.is_compatible ? (
                    <span className="px-2 py-0.5 bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 text-xs rounded-full">
                      维度不匹配
                    </span>
                  ) : embeddingStatus.missing_embeddings > 0 ? (
                    <span className="px-2 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 text-xs rounded-full">
                      {embeddingStatus.missing_embeddings} 个节点缺少向量
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 text-xs rounded-full">
                      状态正常
                    </span>
                  )}
                </div>
              }
              icon="model_training"
              actionLabel={embeddingLoading ? '重建中...' : '重建向量'}
              onAction={handleRebuildEmbeddings}
              loading={embeddingLoading}
              warning={!embeddingStatus.is_compatible}
            />
          )}
        </div>
      </div>

      {/* Recommendations */}
      <div className="bg-indigo-50 dark:bg-indigo-900/20 rounded-xl border border-indigo-200 dark:border-indigo-800 p-6">
        <h2 className="text-lg font-semibold text-indigo-900 dark:text-indigo-300 mb-4 flex items-center gap-2">
          <span className="material-symbols-outlined">lightbulb</span>
          {t('project.maintenance.recommendations.title')}
        </h2>
        <div className="space-y-3">
          <div className="flex items-start gap-3 p-3 bg-white dark:bg-surface-dark rounded-lg border border-indigo-100 dark:border-indigo-800/50 shadow-sm">
            <span className="material-symbols-outlined text-yellow-500 mt-0.5">warning</span>
            <div>
              <p className="font-medium text-slate-900 dark:text-white">
                {t('project.maintenance.recommendations.high_duplication.title')}
              </p>
              <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">
                {t('project.maintenance.recommendations.high_duplication.desc', { count: 45 })}
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-yellow-50 dark:bg-yellow-900/20 rounded-xl border border-yellow-200 dark:border-yellow-800 p-6">
        <h2 className="text-lg font-semibold text-yellow-800 dark:text-yellow-300 mb-2 flex items-center gap-2">
          <span className="material-symbols-outlined">info</span>
          {t('project.maintenance.warning.title')}
        </h2>
        <p className="text-yellow-700 dark:text-yellow-400 text-sm">
          {t('project.maintenance.warning.desc')}
        </p>
      </div>
    </div>
  );
};
