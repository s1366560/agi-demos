/**
 * ProjectSettings Compound Component
 *
 * Management page for project settings with multiple sections:
 * - Basic settings (name, description, visibility)
 * - Memory rules (retention, auto-refresh)
 * - Graph configuration (nodes, edges, similarity)
 * - Advanced operations (export, cache, rebuild)
 * - Danger zone (delete project)
 *
 * Compound component pattern with sub-components:
 * - Header: Page header with title
 * - Message: Success/error message banner
 * - Basic: Basic settings section
 * - Memory: Memory rules section
 * - Graph: Graph configuration section
 * - Advanced: Advanced operations section
 * - Danger: Danger zone section
 * - NoProject: Empty state when no project
 */

import React, { useState, useEffect, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { Input, Modal, message as antdMessage } from 'antd';
import {
  Settings as SettingsIcon,
  Save,
  Trash2,
  Download,
  RefreshCw,
  AlertCircle,
  Box,
  Power,
  RotateCcw,
} from 'lucide-react';

import api, { projectAPI } from '../../services/api';
import { projectSandboxService } from '../../services/projectSandboxService';
import { useProjectStore } from '../../stores/project';
import { confirmAction } from '../../utils/confirmAction';

import type {
  ProjectSettingsHeaderProps,
  ProjectSettingsMessageProps,
  ProjectSettingsBasicProps,
  ProjectSettingsMemoryProps,
  ProjectSettingsGraphProps,
  ProjectSettingsAdvancedProps,
  ProjectSettingsDangerProps,
  ProjectSettingsSandboxProps,
  ProjectSettingsNoProjectProps,
  ProjectSettingsProps,
} from './settings/types';
import type { ProjectSandbox } from '../../types/sandbox';

interface ProjectSettingsError {
  response?: { data?: { detail?: string | undefined } | undefined } | undefined;
  message?: string | undefined;
}

const getProjectSettingsErrorMessage = (error: unknown, fallback: string) => {
  const err = error as ProjectSettingsError;
  return err.response?.data?.detail ?? err.message ?? fallback;
};

// ============================================================================
// Sub-Components
// ============================================================================

// Header Sub-Component
const Header: React.FC<ProjectSettingsHeaderProps> = ({ title }) => (
  <div className="flex items-center space-x-2 mb-6">
    <SettingsIcon className="h-6 w-6 text-gray-600 dark:text-slate-400" />
    <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">{title}</h1>
  </div>
);
Header.displayName = 'ProjectSettings.Header';

// Message Sub-Component
const Message: React.FC<ProjectSettingsMessageProps> = ({ message, onClose }) => {
  const { t } = useTranslation();

  if (!message) return null;

  const isSuccess = message.type === 'success';

  return (
    <div
      className={`p-4 rounded-md ${
        isSuccess
          ? 'bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-300'
          : 'bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-300'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4" />
          {message.text}
        </div>
        <button
          onClick={onClose}
          className="text-current opacity-70 hover:opacity-100"
          aria-label={t('common.close')}
        >
          ×
        </button>
      </div>
    </div>
  );
};
Message.displayName = 'ProjectSettings.Message';

// Basic Settings Sub-Component
const Basic: React.FC<ProjectSettingsBasicProps> = ({
  data,
  isSaving,
  onNameChange,
  onDescriptionChange,
  onIsPublicChange,
  onSave,
}) => {
  const { t } = useTranslation();

  const handleSaveClick = useCallback(() => {
    void onSave();
  }, [onSave]);

  return (
    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
        {t('project.settings.basicTitle')}
      </h2>
      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
            {t('project.settings.basicName')} *
          </label>
          <input
            type="text"
            aria-label={t('project.settings.basicName')}
            value={data.name}
            onChange={(e) => {
              onNameChange(e.target.value);
            }}
            className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
            {t('project.settings.basicDescription')}
          </label>
          <textarea
            aria-label={t('project.settings.basicDescription')}
            value={data.description}
            onChange={(e) => {
              onDescriptionChange(e.target.value);
            }}
            rows={3}
            className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white resize-none"
          />
        </div>

        <div className="flex items-center space-x-2">
          <input
            type="checkbox"
            id="isPublic"
            checked={data.isPublic}
            onChange={(e) => {
              onIsPublicChange(e.target.checked);
            }}
            className="rounded border-gray-300 dark:border-slate-600"
          />
          <label htmlFor="isPublic" className="text-sm text-gray-700 dark:text-slate-300">
            {t('project.settings.basicPublic')}
          </label>
        </div>

        <div className="flex justify-end">
          <button
            onClick={handleSaveClick}
            disabled={isSaving}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            <Save className="h-4 w-4" />
            {isSaving ? t('project.settings.basicSaving') : t('project.settings.basicSave')}
          </button>
        </div>
      </div>
    </div>
  );
};
Basic.displayName = 'ProjectSettings.Basic';

// Memory Rules Sub-Component
const Memory: React.FC<ProjectSettingsMemoryProps> = ({
  data,
  isSaving,
  onMaxEpisodesChange,
  onRetentionDaysChange,
  onAutoRefreshChange,
  onRefreshIntervalChange,
  onSave,
}) => {
  const { t } = useTranslation();

  const handleSaveClick = useCallback(() => {
    void onSave();
  }, [onSave]);

  return (
    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
        {t('project.settings.memoryTitle')}
      </h2>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              {t('project.settings.memoryMaxEpisodes')}
            </label>
            <input
              type="number"
              aria-label={t('project.settings.memoryMaxEpisodes')}
              value={data.maxEpisodes}
              onChange={(e) => {
                onMaxEpisodesChange(Number(e.target.value));
              }}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              {t('project.settings.memoryRetention')}
            </label>
            <input
              type="number"
              aria-label={t('project.settings.memoryRetention')}
              value={data.retentionDays}
              onChange={(e) => {
                onRetentionDaysChange(Number(e.target.value));
              }}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
            />
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <input
            type="checkbox"
            id="autoRefresh"
            checked={data.autoRefresh}
            onChange={(e) => {
              onAutoRefreshChange(e.target.checked);
            }}
            className="rounded border-gray-300 dark:border-slate-600"
          />
          <label htmlFor="autoRefresh" className="text-sm text-gray-700 dark:text-slate-300">
            {t('project.settings.memoryAutoRefresh')}
          </label>
        </div>

        {data.autoRefresh && (
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              {t('project.settings.memoryInterval')}
            </label>
            <input
              type="number"
              aria-label={t('project.settings.memoryInterval')}
              value={data.refreshInterval}
              onChange={(e) => {
                onRefreshIntervalChange(Number(e.target.value));
              }}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
            />
          </div>
        )}

        <div className="flex justify-end">
          <button
            onClick={handleSaveClick}
            disabled={isSaving}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            <Save className="h-4 w-4" />
            {isSaving ? t('project.settings.basicSaving') : t('project.settings.memorySave')}
          </button>
        </div>
      </div>
    </div>
  );
};
Memory.displayName = 'ProjectSettings.Memory';

// Graph Config Sub-Component
const Graph: React.FC<ProjectSettingsGraphProps> = ({
  data,
  isSaving,
  onMaxNodesChange,
  onMaxEdgesChange,
  onSimilarityThresholdChange,
  onCommunityDetectionChange,
  onSave,
}) => {
  const { t } = useTranslation();

  const handleSaveClick = useCallback(() => {
    void onSave();
  }, [onSave]);

  return (
    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
        {t('project.settings.graphTitle')}
      </h2>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              {t('project.settings.graphMaxNodes')}
            </label>
            <input
              type="number"
              aria-label={t('project.settings.graphMaxNodes')}
              value={data.maxNodes}
              onChange={(e) => {
                onMaxNodesChange(Number(e.target.value));
              }}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              {t('project.settings.graphMaxEdges')}
            </label>
            <input
              type="number"
              aria-label={t('project.settings.graphMaxEdges')}
              value={data.maxEdges}
              onChange={(e) => {
                onMaxEdgesChange(Number(e.target.value));
              }}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
            {t('project.settings.graphThreshold')}: {data.similarityThreshold}
          </label>
          <input
            type="range"
            aria-label={t('project.settings.graphThreshold')}
            min="0"
            max="1"
            step="0.05"
            value={data.similarityThreshold}
            onChange={(e) => {
              onSimilarityThresholdChange(Number(e.target.value));
            }}
            className="w-full"
          />
        </div>

        <div className="flex items-center space-x-2">
          <input
            type="checkbox"
            id="communityDetection"
            checked={data.communityDetection}
            onChange={(e) => {
              onCommunityDetectionChange(e.target.checked);
            }}
            className="rounded border-gray-300 dark:border-slate-600"
          />
          <label htmlFor="communityDetection" className="text-sm text-gray-700 dark:text-slate-300">
            {t('project.settings.graphCommunityDetection')}
          </label>
        </div>

        <div className="flex justify-end">
          <button
            onClick={handleSaveClick}
            disabled={isSaving}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            <Save className="h-4 w-4" />
            {isSaving ? t('project.settings.basicSaving') : t('project.settings.graphSave')}
          </button>
        </div>
      </div>
    </div>
  );
};
Graph.displayName = 'ProjectSettings.Graph';

// Advanced Sub-Component
const Advanced: React.FC<ProjectSettingsAdvancedProps> = ({
  onExportData,
  onClearCache,
  onRebuildCommunities,
}) => {
  const { t } = useTranslation();

  const handleExport = useCallback(() => {
    void onExportData();
  }, [onExportData]);

  const handleClearCache = useCallback(() => {
    void onClearCache();
  }, [onClearCache]);

  const handleRebuild = useCallback(() => {
    void onRebuildCommunities();
  }, [onRebuildCommunities]);

  return (
    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
        {t('project.settings.advancedTitle')}
      </h2>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 sm:gap-4">
          <button
            type="button"
            onClick={handleExport}
            className="flex min-h-10 flex-1 items-center justify-center gap-2 rounded-md border border-gray-300 px-4 py-2 text-gray-700 transition-colors hover:bg-gray-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800 sm:flex-none"
          >
            <Download className="h-4 w-4" />
            {t('project.settings.advancedExport')}
          </button>
          <button
            type="button"
            onClick={handleClearCache}
            className="flex min-h-10 flex-1 items-center justify-center gap-2 rounded-md border border-gray-300 px-4 py-2 text-gray-700 transition-colors hover:bg-gray-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800 sm:flex-none"
          >
            <RefreshCw className="h-4 w-4" />
            {t('project.settings.advancedClearCache')}
          </button>
          <button
            type="button"
            onClick={handleRebuild}
            className="flex min-h-10 flex-1 items-center justify-center gap-2 rounded-md border border-gray-300 px-4 py-2 text-gray-700 transition-colors hover:bg-gray-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800 sm:flex-none"
          >
            <RefreshCw className="h-4 w-4" />
            {t('project.settings.advancedRebuild')}
          </button>
        </div>
      </div>
    </div>
  );
};
Advanced.displayName = 'ProjectSettings.Advanced';

// Danger Zone Sub-Component
const Danger: React.FC<ProjectSettingsDangerProps> = ({ projectName: _projectName, onDelete }) => {
  const { t } = useTranslation();

  const handleDelete = useCallback(() => {
    void onDelete();
  }, [onDelete]);

  return (
    <div className="bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800 p-6">
      <h2 className="text-lg font-semibold text-red-900 dark:text-red-300 mb-4">
        {t('project.settings.dangerTitle')}
      </h2>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm text-red-800 dark:text-red-300 mb-1">
            {t('project.settings.dangerDesc')}
          </p>
          <p className="text-xs text-red-600 dark:text-red-400">
            {t('project.settings.dangerWarning')}
          </p>
        </div>
        <button
          type="button"
          onClick={handleDelete}
          className="flex min-h-10 items-center justify-center gap-2 rounded-md bg-red-600 px-4 py-2 text-white transition-colors hover:bg-red-700 sm:flex-none"
        >
          <Trash2 className="h-4 w-4" />
          {t('project.settings.dangerDelete')}
        </button>
      </div>
    </div>
  );
};
Danger.displayName = 'ProjectSettings.Danger';

// NoProject Sub-Component
const NoProject: React.FC<ProjectSettingsNoProjectProps> = () => {
  const { t } = useTranslation();

  return (
    <div className="p-8 text-center text-slate-500">
      <SettingsIcon className="h-12 w-12 mx-auto mb-3 opacity-50" />
      <p>{t('project.settings.noProject')}</p>
    </div>
  );
};
NoProject.displayName = 'ProjectSettings.NoProject';

// Sandbox Sub-Component
const Sandbox: React.FC<ProjectSettingsSandboxProps> = ({ projectId }) => {
  const { t } = useTranslation();
  const [sandboxInfo, setSandboxInfo] = useState<ProjectSandbox | null>(null);
  const [stats, setStats] = useState<{
    cpu_percent?: number;
    memory_used_mb?: number;
    memory_limit_mb?: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);

  const fetchSandboxInfo = useCallback(async () => {
    try {
      setLoading(true);
      const info = await projectSandboxService.getProjectSandbox(projectId);
      setSandboxInfo(info);
      // Only fetch stats if sandbox is running
      if (info?.status === 'running') {
        try {
          const statsData = await projectSandboxService.getStats(projectId);
          setStats(statsData);
        } catch {
          setStats(null);
        }
      } else {
        setStats(null);
      }
    } catch {
      setSandboxInfo(null);
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void fetchSandboxInfo();
  }, [fetchSandboxInfo]);

  const handleRestart = useCallback(async () => {
    setActionLoading(true);
    try {
      await projectSandboxService.restartSandbox(projectId);
      await fetchSandboxInfo();
    } finally {
      setActionLoading(false);
    }
  }, [projectId, fetchSandboxInfo]);

  const handleTerminate = useCallback(async () => {
    setActionLoading(true);
    try {
      await projectSandboxService.terminateSandbox(projectId);
      await fetchSandboxInfo();
    } finally {
      setActionLoading(false);
    }
  }, [projectId, fetchSandboxInfo]);

  const statusColor =
    sandboxInfo?.status === 'running'
      ? 'text-green-500'
      : sandboxInfo?.status === 'terminated'
        ? 'text-gray-400'
        : sandboxInfo?.status === 'error'
          ? 'text-red-500'
          : 'text-yellow-500';

  return (
    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6">
      <div className="flex items-center gap-2 mb-4">
        <Box className="h-5 w-5 text-purple-500" />
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
          {t('project.settings.sandboxSectionTitle')}
        </h3>
      </div>
      <p className="text-sm text-gray-500 dark:text-slate-400 mb-4">
        {t('project.settings.sandboxDescription')}
      </p>

      {loading ? (
        <div className="text-sm text-gray-400">{t('project.settings.sandboxLoading')}</div>
      ) : !sandboxInfo ? (
        <div className="text-sm text-gray-500 dark:text-slate-400">
          {t('project.settings.sandboxEmpty')}
        </div>
      ) : (
        <div className="space-y-4">
          {/* Status Row */}
          <div className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
            <div>
              <span className="text-gray-500 dark:text-slate-400">
                {t('project.settings.sandboxStatusLabel')}:
              </span>{' '}
              <span className={`font-medium ${statusColor}`}>{sandboxInfo.status}</span>
            </div>
            <div>
              <span className="text-gray-500 dark:text-slate-400">
                {t('project.settings.sandboxIdLabel')}:
              </span>{' '}
              <span className="break-all font-mono text-xs text-gray-600 dark:text-slate-300">
                {sandboxInfo.sandbox_id ? sandboxInfo.sandbox_id.slice(0, 12) + '...' : '-'}
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
                {new Date(sandboxInfo.last_accessed_at).toLocaleString()}
              </span>
            </div>
          )}

          {/* Resource Stats (only when running) */}
          {stats && (
            <div className="grid grid-cols-1 gap-4 rounded-md bg-gray-50 p-3 text-sm dark:bg-slate-800/50 sm:grid-cols-2">
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
          <div className="flex flex-wrap gap-2 pt-2 sm:gap-3">
            <button
              type="button"
              onClick={() => {
                void handleRestart();
              }}
              disabled={actionLoading || sandboxInfo.status === 'terminated'}
              className="inline-flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700 sm:flex-none"
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
              className="inline-flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-600 dark:bg-slate-800 dark:text-red-400 dark:hover:bg-red-900/20 sm:flex-none"
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
              className="inline-flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700 sm:flex-none"
            >
              <RefreshCw className="h-4 w-4" />
              {t('common.refresh')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
Sandbox.displayName = 'ProjectSettings.Sandbox';

// ============================================================================
// Main Component
// ============================================================================

export const ProjectSettings: React.FC<ProjectSettingsProps> & {
  Header: typeof Header;
  Message: typeof Message;
  Basic: typeof Basic;
  Memory: typeof Memory;
  Graph: typeof Graph;
  Advanced: typeof Advanced;
  Sandbox: typeof Sandbox;
  Danger: typeof Danger;
  NoProject: typeof NoProject;
} = ({ className = '' }) => {
  const { t } = useTranslation();
  const { currentProject } = useProjectStore();
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Basic settings
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isPublic, setIsPublic] = useState(false);

  // Memory rules
  const [maxEpisodes, setMaxEpisodes] = useState(100);
  const [retentionDays, setRetentionDays] = useState(365);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [refreshInterval, setRefreshInterval] = useState(24);

  // Graph configuration
  const [maxNodes, setMaxNodes] = useState(10000);
  const [maxEdges, setMaxEdges] = useState(50000);
  const [similarityThreshold, setSimilarityThreshold] = useState(0.8);
  const [communityDetection, setCommunityDetection] = useState(true);

  // Load project data
  useEffect(() => {
    if (currentProject) {
      setName(currentProject.name || '');
      setDescription(currentProject.description || '');
      setIsPublic(currentProject.is_public || false);

      setMaxEpisodes(currentProject.memory_rules.max_episodes || 100);
      setRetentionDays(currentProject.memory_rules.retention_days || 365);
      setAutoRefresh(currentProject.memory_rules.auto_refresh);
      setRefreshInterval(currentProject.memory_rules.refresh_interval || 24);

      setMaxNodes(currentProject.graph_config.max_nodes || 10000);
      setMaxEdges(currentProject.graph_config.max_edges || 50000);
      setSimilarityThreshold(currentProject.graph_config.similarity_threshold || 0.8);
      setCommunityDetection(currentProject.graph_config.community_detection);
    }
  }, [currentProject]);

  // Handlers
  const handleSaveBasicSettings = useCallback(async () => {
    if (!currentProject) return;

    setIsSaving(true);
    setMessage(null);

    try {
      await projectAPI.update(currentProject.tenant_id, currentProject.id, {
        name,
        description,
        is_public: isPublic,
      });
      setMessage({ type: 'success', text: t('project.settings.saved') });
      setTimeout(() => {
        window.location.reload();
      }, 1000);
    } catch (error) {
      console.error('Failed to save settings:', error);
      const fallback = t('project.settings.failed');
      setMessage({
        type: 'error',
        text: `${fallback}: ${getProjectSettingsErrorMessage(error, fallback)}`,
      });
    } finally {
      setIsSaving(false);
    }
  }, [currentProject, name, description, isPublic, t]);

  const handleSaveMemoryRules = useCallback(async () => {
    if (!currentProject) return;

    setIsSaving(true);
    setMessage(null);

    try {
      await projectAPI.update(currentProject.tenant_id, currentProject.id, {
        memory_rules: {
          max_episodes: maxEpisodes,
          retention_days: retentionDays,
          auto_refresh: autoRefresh,
          refresh_interval: refreshInterval,
        },
      });
      setMessage({ type: 'success', text: t('project.settings.saved') });
    } catch (error) {
      console.error('Failed to save memory rules:', error);
      const fallback = t('project.settings.failed');
      setMessage({
        type: 'error',
        text: `${fallback}: ${getProjectSettingsErrorMessage(error, fallback)}`,
      });
    } finally {
      setIsSaving(false);
    }
  }, [currentProject, maxEpisodes, retentionDays, autoRefresh, refreshInterval, t]);

  const handleSaveGraphConfig = useCallback(async () => {
    if (!currentProject) return;

    setIsSaving(true);
    setMessage(null);

    try {
      await projectAPI.update(currentProject.tenant_id, currentProject.id, {
        graph_config: {
          max_nodes: maxNodes,
          max_edges: maxEdges,
          similarity_threshold: similarityThreshold,
          community_detection: communityDetection,
        },
      });
      setMessage({ type: 'success', text: t('project.settings.saved') });
    } catch (error) {
      console.error('Failed to save graph config:', error);
      const fallback = t('project.settings.failed');
      setMessage({
        type: 'error',
        text: `${fallback}: ${getProjectSettingsErrorMessage(error, fallback)}`,
      });
    } finally {
      setIsSaving(false);
    }
  }, [currentProject, maxNodes, maxEdges, similarityThreshold, communityDetection, t]);

  const handleClearCache = useCallback(async () => {
    if (!currentProject) return;

    if (
      !(await confirmAction({ title: t('project.settings.advancedConfirmClear'), danger: true }))
    ) {
      return;
    }

    setMessage(null);
    try {
      await api.post('/maintenance/refresh/incremental', {
        rebuild_communities: true,
      });
      setMessage({ type: 'success', text: t('project.settings.advancedClearCacheSuccess') });
    } catch (error) {
      console.error('Failed to clear cache:', error);
      setMessage({ type: 'error', text: t('project.settings.advancedClearCacheError') });
    }
  }, [currentProject, t]);

  const handleRebuildCommunities = useCallback(async () => {
    if (!currentProject) return;

    if (
      !(await confirmAction({ title: t('project.settings.advancedConfirmRebuild'), danger: true }))
    ) {
      return;
    }

    setMessage(null);
    try {
      await api.post('/graph/communities/rebuild');
      setMessage({ type: 'success', text: t('project.settings.advancedRebuildSuccess') });
    } catch (error) {
      console.error('Failed to rebuild communities:', error);
      setMessage({ type: 'error', text: t('project.settings.advancedRebuildError') });
    }
  }, [currentProject, t]);

  const handleExportData = useCallback(async () => {
    if (!currentProject) return;

    setMessage(null);
    try {
      const data = await api.post('/data/export', {
        tenant_id: currentProject.tenant_id,
        include_episodes: true,
        include_entities: true,
        include_relationships: true,
        include_communities: true,
      });

      const jsonString = JSON.stringify(data, null, 2);
      const blob = new Blob([jsonString], { type: 'application/json' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      const exportDate = new Date().toISOString().slice(0, 10);
      link.href = url;
      link.download = `project-${currentProject.id}-export-${exportDate}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);

      setMessage({ type: 'success', text: t('project.settings.advancedExportSuccess') });
    } catch (error) {
      console.error('Failed to export data:', error);
      setMessage({ type: 'error', text: t('project.settings.advancedExportError') });
    }
  }, [currentProject, t]);

  const handleDeleteProject = useCallback(async () => {
    if (!currentProject) return;

    let confirmText = '';
    const confirmed = await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: t('project.settings.dangerConfirmPrompt'),
        content: (
          <Input
            aria-label={t('project.settings.dangerConfirmPrompt')}
            autoFocus
            placeholder={currentProject.name}
            onChange={(event) => {
              confirmText = event.target.value;
            }}
          />
        ),
        okButtonProps: { danger: true },
        centered: true,
        onOk: () => {
          if (confirmText !== currentProject.name) {
            void antdMessage.error(t('project.settings.dangerNameMismatch'));
            return Promise.reject(new Error(t('project.settings.dangerNameMismatch')));
          }
          resolve(true);
          return undefined;
        },
        onCancel: () => {
          resolve(false);
        },
      });
    });
    if (!confirmed) {
      return;
    }

    try {
      await projectAPI.delete(currentProject.tenant_id, currentProject.id);
      void antdMessage.success(t('project.settings.dangerSuccess'));
      window.location.href = '/tenant';
    } catch (error) {
      console.error('Failed to delete project:', error);
      void antdMessage.error(t('project.settings.dangerFail'));
    }
  }, [currentProject, t]);

  const clearMessage = useCallback(() => {
    setMessage(null);
  }, []);

  // No project state
  if (!currentProject) {
    return <NoProject />;
  }

  return (
    <div className={`space-y-6 p-4 sm:p-6 lg:p-8 ${className}`}>
      <Header title={t('project.settings.title')} />
      <Message message={message} onClose={clearMessage} />
      <Basic
        data={{ name, description, isPublic }}
        isSaving={isSaving}
        onNameChange={setName}
        onDescriptionChange={setDescription}
        onIsPublicChange={setIsPublic}
        onSave={handleSaveBasicSettings}
      />
      <Memory
        data={{ maxEpisodes, retentionDays, autoRefresh, refreshInterval }}
        isSaving={isSaving}
        onMaxEpisodesChange={setMaxEpisodes}
        onRetentionDaysChange={setRetentionDays}
        onAutoRefreshChange={setAutoRefresh}
        onRefreshIntervalChange={setRefreshInterval}
        onSave={handleSaveMemoryRules}
      />
      <Graph
        data={{ maxNodes, maxEdges, similarityThreshold, communityDetection }}
        isSaving={isSaving}
        onMaxNodesChange={setMaxNodes}
        onMaxEdgesChange={setMaxEdges}
        onSimilarityThresholdChange={setSimilarityThreshold}
        onCommunityDetectionChange={setCommunityDetection}
        onSave={handleSaveGraphConfig}
      />
      <Advanced
        onExportData={handleExportData}
        onClearCache={handleClearCache}
        onRebuildCommunities={handleRebuildCommunities}
      />
      <Sandbox projectId={currentProject.id} />
      <Danger projectName={currentProject.name} onDelete={handleDeleteProject} />
    </div>
  );
};

ProjectSettings.displayName = 'ProjectSettings';

// Attach sub-components
ProjectSettings.Header = Header;
ProjectSettings.Message = Message;
ProjectSettings.Basic = Basic;
ProjectSettings.Memory = Memory;
ProjectSettings.Graph = Graph;
ProjectSettings.Advanced = Advanced;
ProjectSettings.Sandbox = Sandbox;
ProjectSettings.Danger = Danger;
ProjectSettings.NoProject = NoProject;

export default ProjectSettings;
