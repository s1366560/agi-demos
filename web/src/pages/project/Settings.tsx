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
import { useNavigate } from 'react-router-dom';

import { Input, Modal, message as antdMessage } from 'antd';
import {
  Settings as SettingsIcon,
  Save,
  Trash2,
  Download,
  RefreshCw,
  AlertCircle,
  Loader2,
  Power,
  RotateCcw,
  Database,
  Network,
  Server,
  ShieldAlert,
  SlidersHorizontal,
  Wrench,
} from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { formatDateTime } from '@/utils/date';

import api, { projectAPI } from '../../services/api';
import { projectSandboxService } from '../../services/projectSandboxService';
import { useProjectStore } from '../../stores/project';
import { confirmAction } from '../../utils/confirmAction';
import { logger } from '../../utils/logger';

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

const panelClass =
  'rounded-md bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.08)] dark:bg-slate-950 dark:shadow-[0_0_0_1px_rgba(148,163,184,0.16)]';

const fieldClass =
  'h-9 w-full rounded border border-gray-200 bg-white px-3 text-sm text-gray-950 outline-none transition-colors placeholder:text-gray-400 focus:border-gray-900 focus:ring-2 focus:ring-gray-950/10 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:focus:border-slate-300 dark:focus:ring-white/10';

const textareaClass = `${fieldClass} h-auto min-h-24 py-2 resize-none`;

const secondaryButtonClass =
  'inline-flex min-h-9 items-center justify-center gap-2 rounded border border-gray-200 bg-white px-3 text-sm font-medium text-gray-900 transition-colors hover:border-gray-300 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:hover:border-slate-600 dark:hover:bg-slate-900';

const primaryButtonClass =
  'inline-flex min-h-9 items-center justify-center gap-2 rounded bg-gray-950 px-3 text-sm font-medium text-white transition-colors hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-gray-950 dark:hover:bg-slate-200';

const dangerButtonClass =
  'inline-flex min-h-9 items-center justify-center gap-2 rounded bg-red-600 px-3 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50';

interface SettingsSectionProps {
  id?: string;
  icon: React.ReactNode;
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  tone?: 'default' | 'danger';
}

const SettingsSection: React.FC<SettingsSectionProps> = ({
  id,
  icon,
  title,
  aside,
  children,
  tone = 'default',
}) => (
  <section
    id={id}
    className={`${panelClass} overflow-hidden ${
      tone === 'danger' ? 'shadow-[0_0_0_1px_rgba(220,38,38,0.22)]' : ''
    }`}
  >
    <div className="flex flex-col gap-3 border-b border-gray-100 px-5 py-4 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-center gap-3">
        <div
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded border ${
            tone === 'danger'
              ? 'border-red-200 bg-red-50 text-red-600 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300'
              : 'border-gray-200 bg-gray-50 text-gray-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300'
          }`}
        >
          {icon}
        </div>
        <h2
          className={`truncate text-base font-semibold ${
            tone === 'danger' ? 'text-red-900 dark:text-red-200' : 'text-gray-950 dark:text-white'
          }`}
        >
          {title}
        </h2>
      </div>
      {aside}
    </div>
    <div className="p-5">{children}</div>
  </section>
);

interface FieldProps {
  label: string;
  children: React.ReactNode;
  span?: 'full';
}

const Field: React.FC<FieldProps> = ({ label, children, span }) => (
  <label className={`block min-w-0 ${span === 'full' ? 'sm:col-span-2' : ''}`}>
    <span className="mb-1.5 block text-xs font-medium text-gray-600 dark:text-slate-400">
      {label}
    </span>
    {children}
  </label>
);

interface ToggleRowProps {
  id: string;
  checked: boolean;
  label: string;
  onChange: (checked: boolean) => void;
  tone?: 'default' | 'danger';
}

const ToggleRow: React.FC<ToggleRowProps> = ({
  id,
  checked,
  label,
  onChange,
  tone = 'default',
}) => (
  <label
    htmlFor={id}
    className={`flex cursor-pointer items-center justify-between gap-4 rounded border px-3 py-2.5 transition-colors ${
      tone === 'danger'
        ? 'border-red-200 bg-red-50/70 text-red-900 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200'
        : 'border-gray-200 bg-gray-50 text-gray-800 hover:bg-gray-100 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-200 dark:hover:bg-slate-900'
    }`}
  >
    <span className="text-sm font-medium">{label}</span>
    <input
      type="checkbox"
      id={id}
      checked={checked}
      onChange={(e) => {
        onChange(e.target.checked);
      }}
      className="h-4 w-4 rounded border-gray-300 text-gray-950 focus:ring-gray-950 dark:border-slate-600 dark:bg-slate-900 dark:text-white dark:focus:ring-white"
    />
  </label>
);

interface SaveButtonProps {
  isSaving: boolean;
  label: string;
  savingLabel: string;
  onClick: () => void;
}

const SaveButton: React.FC<SaveButtonProps> = ({ isSaving, label, savingLabel, onClick }) => (
  <button type="button" onClick={onClick} disabled={isSaving} className={primaryButtonClass}>
    {isSaving ? (
      <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
    ) : (
      <Save className="h-4 w-4" aria-hidden="true" />
    )}
    {isSaving ? savingLabel : label}
  </button>
);

// ============================================================================
// Sub-Components
// ============================================================================

// Header Sub-Component
const Header: React.FC<ProjectSettingsHeaderProps> = ({ title }) => (
  <div className="flex flex-col gap-2 border-b border-gray-100 pb-5 dark:border-slate-800 sm:flex-row sm:items-end sm:justify-between">
    <div className="min-w-0">
      <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-normal text-gray-500 dark:text-slate-500">
        <SettingsIcon className="h-4 w-4" />
        MemStack
      </div>
      <h1 className="truncate text-2xl font-semibold tracking-normal text-gray-950 dark:text-white">
        {title}
      </h1>
    </div>
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
      role={isSuccess ? 'status' : 'alert'}
      className={`rounded-md px-4 py-3 text-sm shadow-[0_0_0_1px_rgba(0,0,0,0.08)] ${
        isSuccess
          ? 'bg-green-50 text-green-800 dark:bg-green-950/30 dark:text-green-300'
          : 'bg-red-50 text-red-800 dark:bg-red-950/30 dark:text-red-300'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          {message.text}
        </div>
        <button
          type="button"
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
    <SettingsSection
      id="basic"
      icon={<SlidersHorizontal className="h-4 w-4" />}
      title={t('project.settings.basicTitle')}
      aside={
        <SaveButton
          isSaving={isSaving}
          label={t('project.settings.basicSave')}
          savingLabel={t('project.settings.basicSaving')}
          onClick={handleSaveClick}
        />
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={`${t('project.settings.basicName')} *`} span="full">
          <input
            type="text"
            required
            aria-label={t('project.settings.basicName')}
            value={data.name}
            onChange={(e) => {
              onNameChange(e.target.value);
            }}
            className={fieldClass}
          />
        </Field>

        <Field label={t('project.settings.basicDescription')} span="full">
          <textarea
            aria-label={t('project.settings.basicDescription')}
            value={data.description}
            onChange={(e) => {
              onDescriptionChange(e.target.value);
            }}
            rows={3}
            className={textareaClass}
          />
        </Field>

        <div className="sm:col-span-2">
          <ToggleRow
            id="isPublic"
            checked={data.isPublic}
            label={t('project.settings.basicPublic')}
            onChange={onIsPublicChange}
          />
        </div>
      </div>
    </SettingsSection>
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
    <SettingsSection
      id="memory"
      icon={<Database className="h-4 w-4" />}
      title={t('project.settings.memoryTitle')}
      aside={
        <SaveButton
          isSaving={isSaving}
          label={t('project.settings.memorySave')}
          savingLabel={t('project.settings.basicSaving')}
          onClick={handleSaveClick}
        />
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('project.settings.memoryMaxEpisodes')}>
          <input
            type="number"
            min={1}
            inputMode="numeric"
            aria-label={t('project.settings.memoryMaxEpisodes')}
            value={data.maxEpisodes}
            onChange={(e) => {
              const next = e.target.valueAsNumber;
              if (!Number.isNaN(next)) onMaxEpisodesChange(next);
            }}
            className={fieldClass}
          />
        </Field>
        <Field label={t('project.settings.memoryRetention')}>
          <input
            type="number"
            min={1}
            inputMode="numeric"
            aria-label={t('project.settings.memoryRetention')}
            value={data.retentionDays}
            onChange={(e) => {
              const next = e.target.valueAsNumber;
              if (!Number.isNaN(next)) onRetentionDaysChange(next);
            }}
            className={fieldClass}
          />
        </Field>

        <div className="sm:col-span-2">
          <ToggleRow
            id="autoRefresh"
            checked={data.autoRefresh}
            label={t('project.settings.memoryAutoRefresh')}
            onChange={onAutoRefreshChange}
          />
        </div>

        {data.autoRefresh && (
          <Field label={t('project.settings.memoryInterval')} span="full">
            <input
              type="number"
              min={1}
              inputMode="numeric"
              aria-label={t('project.settings.memoryInterval')}
              value={data.refreshInterval}
              onChange={(e) => {
                const next = e.target.valueAsNumber;
                if (!Number.isNaN(next)) onRefreshIntervalChange(next);
              }}
              className={fieldClass}
            />
          </Field>
        )}
      </div>
    </SettingsSection>
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
    <SettingsSection
      id="graph"
      icon={<Network className="h-4 w-4" />}
      title={t('project.settings.graphTitle')}
      aside={
        <SaveButton
          isSaving={isSaving}
          label={t('project.settings.graphSave')}
          savingLabel={t('project.settings.basicSaving')}
          onClick={handleSaveClick}
        />
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('project.settings.graphMaxNodes')}>
          <input
            type="number"
            min={1}
            inputMode="numeric"
            aria-label={t('project.settings.graphMaxNodes')}
            value={data.maxNodes}
            onChange={(e) => {
              const next = e.target.valueAsNumber;
              if (!Number.isNaN(next)) onMaxNodesChange(next);
            }}
            className={fieldClass}
          />
        </Field>
        <Field label={t('project.settings.graphMaxEdges')}>
          <input
            type="number"
            min={1}
            inputMode="numeric"
            aria-label={t('project.settings.graphMaxEdges')}
            value={data.maxEdges}
            onChange={(e) => {
              const next = e.target.valueAsNumber;
              if (!Number.isNaN(next)) onMaxEdgesChange(next);
            }}
            className={fieldClass}
          />
        </Field>

        <div className="sm:col-span-2">
          <div className="mb-2 flex items-center justify-between gap-4">
            <span className="text-xs font-medium text-gray-600 dark:text-slate-400">
              {t('project.settings.graphThreshold')}
            </span>
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-900 dark:bg-slate-800 dark:text-slate-100">
              {data.similarityThreshold}
            </span>
          </div>
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
            className="h-2 w-full accent-gray-950 dark:accent-white"
          />
        </div>

        <div className="sm:col-span-2">
          <ToggleRow
            id="communityDetection"
            checked={data.communityDetection}
            label={t('project.settings.graphCommunityDetection')}
            onChange={onCommunityDetectionChange}
          />
        </div>
      </div>
    </SettingsSection>
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
    <SettingsSection
      id="advanced"
      icon={<Wrench className="h-4 w-4" />}
      title={t('project.settings.advancedTitle')}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <button type="button" onClick={handleExport} className={secondaryButtonClass}>
          <Download className="h-4 w-4" />
          {t('project.settings.advancedExport')}
        </button>
        <button type="button" onClick={handleClearCache} className={secondaryButtonClass}>
          <RefreshCw className="h-4 w-4" />
          {t('project.settings.advancedClearCache')}
        </button>
        <button type="button" onClick={handleRebuild} className={secondaryButtonClass}>
          <RefreshCw className="h-4 w-4" />
          {t('project.settings.advancedRebuild')}
        </button>
      </div>
    </SettingsSection>
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
    <SettingsSection
      id="danger"
      icon={<ShieldAlert className="h-4 w-4" />}
      title={t('project.settings.dangerTitle')}
      tone="danger"
    >
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
          className={`${dangerButtonClass} sm:flex-none`}
        >
          <Trash2 className="h-4 w-4" />
          {t('project.settings.dangerDelete')}
        </button>
      </div>
    </SettingsSection>
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
      void antdMessage.success(t('project.settings.sandboxRestartSuccess', 'Sandbox restarted'));
      await fetchSandboxInfo();
    } catch (error) {
      logger.error('[ProjectSettings] Failed to restart sandbox:', error);
      void antdMessage.error(t('project.settings.sandboxActionFailed', 'Sandbox action failed'));
    } finally {
      setActionLoading(false);
    }
  }, [projectId, fetchSandboxInfo, t]);

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
      await projectSandboxService.terminateSandbox(projectId);
      void antdMessage.success(t('project.settings.sandboxTerminateSuccess', 'Sandbox terminated'));
      await fetchSandboxInfo();
    } catch (error) {
      logger.error('[ProjectSettings] Failed to terminate sandbox:', error);
      void antdMessage.error(t('project.settings.sandboxActionFailed', 'Sandbox action failed'));
    } finally {
      setActionLoading(false);
    }
  }, [projectId, fetchSandboxInfo, t]);

  const statusColor =
    sandboxInfo?.status === 'running'
      ? 'text-green-600 dark:text-green-400'
      : sandboxInfo?.status === 'terminated'
        ? 'text-gray-500 dark:text-slate-500'
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
    </SettingsSection>
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
  const navigate = useNavigate();
  const { currentProject, updateProject } = useProjectStore(
    useShallow((state) => ({
      currentProject: state.currentProject,
      updateProject: state.updateProject,
    }))
  );
  const [savingSection, setSavingSection] = useState<'basic' | 'memory' | 'graph' | null>(null);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [activeSection, setActiveSection] = useState('basic');

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
    if (!currentProject || savingSection) return;

    if (!name.trim()) {
      setMessage({ type: 'error', text: t('project.settings.nameRequired', 'Name is required.') });
      return;
    }

    setSavingSection('basic');
    setMessage(null);

    try {
      await updateProject(currentProject.tenant_id, currentProject.id, {
        name: name.trim(),
        description,
        is_public: isPublic,
      });
      setMessage({ type: 'success', text: t('project.settings.saved') });
    } catch (error) {
      logger.error('[ProjectSettings] Failed to save settings:', error);
      const fallback = t('project.settings.failed');
      setMessage({
        type: 'error',
        text: `${fallback}: ${getProjectSettingsErrorMessage(error, fallback)}`,
      });
    } finally {
      setSavingSection(null);
    }
  }, [currentProject, updateProject, name, description, isPublic, savingSection, t]);

  const handleSaveMemoryRules = useCallback(async () => {
    if (!currentProject || savingSection) return;

    setSavingSection('memory');
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
      logger.error('[ProjectSettings] Failed to save memory rules:', error);
      const fallback = t('project.settings.failed');
      setMessage({
        type: 'error',
        text: `${fallback}: ${getProjectSettingsErrorMessage(error, fallback)}`,
      });
    } finally {
      setSavingSection(null);
    }
  }, [currentProject, maxEpisodes, retentionDays, autoRefresh, refreshInterval, savingSection, t]);

  const handleSaveGraphConfig = useCallback(async () => {
    if (!currentProject || savingSection) return;

    setSavingSection('graph');
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
      logger.error('[ProjectSettings] Failed to save graph config:', error);
      const fallback = t('project.settings.failed');
      setMessage({
        type: 'error',
        text: `${fallback}: ${getProjectSettingsErrorMessage(error, fallback)}`,
      });
    } finally {
      setSavingSection(null);
    }
  }, [
    currentProject,
    maxNodes,
    maxEdges,
    similarityThreshold,
    communityDetection,
    savingSection,
    t,
  ]);

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
        project_id: currentProject.id,
        rebuild_communities: true,
      });
      setMessage({ type: 'success', text: t('project.settings.advancedClearCacheSuccess') });
    } catch (error) {
      logger.error('[ProjectSettings] Failed to clear cache:', error);
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
      await api.post(
        `/graph/communities/rebuild?project_id=${encodeURIComponent(currentProject.id)}`
      );
      setMessage({ type: 'success', text: t('project.settings.advancedRebuildSuccess') });
    } catch (error) {
      logger.error('[ProjectSettings] Failed to rebuild communities:', error);
      setMessage({ type: 'error', text: t('project.settings.advancedRebuildError') });
    }
  }, [currentProject, t]);

  const handleExportData = useCallback(async () => {
    if (!currentProject) return;

    setMessage(null);
    try {
      const data = await api.post('/data/export', {
        tenant_id: currentProject.tenant_id,
        project_id: currentProject.id,
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
      logger.error('[ProjectSettings] Failed to export data:', error);
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
      void navigate('/tenant');
    } catch (error) {
      logger.error('[ProjectSettings] Failed to delete project:', error);
      void antdMessage.error(t('project.settings.dangerFail'));
    }
  }, [currentProject, navigate, t]);

  const clearMessage = useCallback(() => {
    setMessage(null);
  }, []);

  // No project state
  if (!currentProject) {
    return <NoProject />;
  }

  const sectionLinks = [
    { href: '#basic', label: t('project.settings.basicTitle'), icon: SlidersHorizontal },
    { href: '#memory', label: t('project.settings.memoryTitle'), icon: Database },
    { href: '#graph', label: t('project.settings.graphTitle'), icon: Network },
    { href: '#advanced', label: t('project.settings.advancedTitle'), icon: Wrench },
    { href: '#sandbox', label: t('project.settings.sandboxSectionTitle'), icon: Server },
    { href: '#danger', label: t('project.settings.dangerTitle'), icon: ShieldAlert },
  ];

  return (
    <div className={`min-h-full bg-gray-50/70 p-4 dark:bg-slate-950 sm:p-6 lg:p-8 ${className}`}>
      <Header title={t('project.settings.title')} />
      <Message message={message} onClose={clearMessage} />
      <div className="mt-6 grid gap-6 lg:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="lg:sticky lg:top-20 lg:self-start">
          <div className={`${panelClass} overflow-hidden`}>
            <div className="border-b border-gray-100 px-4 py-4 dark:border-slate-800">
              <p className="truncate text-sm font-semibold text-gray-950 dark:text-white">{name}</p>
              <p className="mt-1 line-clamp-2 text-xs text-gray-500 dark:text-slate-500">
                {description || t('project.settings.basicDescription')}
              </p>
            </div>
            <nav className="p-2">
              {sectionLinks.map(({ href, label, icon: Icon }) => {
                const sectionId = href.slice(1);
                const isActive = activeSection === sectionId;
                return (
                  <a
                    key={href}
                    href={href}
                    aria-current={isActive ? 'location' : undefined}
                    onClick={() => {
                      setActiveSection(sectionId);
                    }}
                    className={`flex min-h-9 items-center gap-2 rounded px-2 text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-gray-100 text-gray-950 dark:bg-slate-900 dark:text-white'
                        : 'text-gray-600 hover:bg-gray-100 hover:text-gray-950 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-white'
                    }`}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                    <span className="truncate">{label}</span>
                  </a>
                );
              })}
            </nav>
          </div>
        </aside>

        <div className="space-y-5">
          <Basic
            data={{ name, description, isPublic }}
            isSaving={savingSection === 'basic'}
            onNameChange={setName}
            onDescriptionChange={setDescription}
            onIsPublicChange={setIsPublic}
            onSave={handleSaveBasicSettings}
          />
          <Memory
            data={{ maxEpisodes, retentionDays, autoRefresh, refreshInterval }}
            isSaving={savingSection === 'memory'}
            onMaxEpisodesChange={setMaxEpisodes}
            onRetentionDaysChange={setRetentionDays}
            onAutoRefreshChange={setAutoRefresh}
            onRefreshIntervalChange={setRefreshInterval}
            onSave={handleSaveMemoryRules}
          />
          <Graph
            data={{ maxNodes, maxEdges, similarityThreshold, communityDetection }}
            isSaving={savingSection === 'graph'}
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
      </div>
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
