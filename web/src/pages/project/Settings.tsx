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

import {
  Settings as SettingsIcon,
  Save,
  Trash2,
  Download,
  RefreshCw,
  AlertCircle,
} from 'lucide-react';

import api, { projectAPI } from '../../services/api';
import { useProjectStore } from '../../stores/project';

import type {
  ProjectSettingsHeaderProps,
  ProjectSettingsMessageProps,
  ProjectSettingsBasicProps,
  ProjectSettingsMemoryProps,
  ProjectSettingsGraphProps,
  ProjectSettingsAdvancedProps,
  ProjectSettingsDangerProps,
  ProjectSettingsNoProjectProps,
  ProjectSettingsProps,
} from './settings/types';

const TEXTS = {
  title: 'Project Settings',
  noProject: 'No project selected',
  messages: {
    saved: 'Settings saved successfully',
    failed: 'Failed to save settings',
  },
  basic: {
    title: 'Basic Settings',
    name: 'Project Name',
    description: 'Description',
    public: 'Make project public',
    save: 'Save',
    saving: 'Saving...',
  },
  memory: {
    title: 'Memory Rules',
    max_episodes: 'Max Episodes',
    retention: 'Retention Days',
    auto_refresh: 'Auto Refresh',
    interval: 'Refresh Interval (hours)',
    save: 'Save',
  },
  graph: {
    title: 'Graph Configuration',
    max_nodes: 'Max Nodes',
    max_edges: 'Max Edges',
    threshold: 'Similarity Threshold',
    save: 'Save',
  },
  advanced: {
    title: 'Advanced',
    export: 'Export Data',
    clear_cache: 'Clear Cache',
    rebuild: 'Rebuild Communities',
    confirm_clear: 'Are you sure you want to clear the cache?',
    confirm_rebuild: 'Are you sure you want to rebuild communities?',
  },
  danger: {
    title: 'Danger Zone',
    desc: 'Once you delete a project, there is no going back. Please be certain.',
    warning: 'This action cannot be undone.',
    delete: 'Delete Project',
    confirm_prompt: 'Type project name to confirm:',
    name_mismatch: 'Project name does not match.',
    success: 'Project deleted successfully.',
    fail: 'Failed to delete project.',
  },
} as const;

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
          aria-label="Close"
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
  const handleSaveClick = useCallback(() => {
    onSave();
  }, [onSave]);

  return (
    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
        {TEXTS.basic.title}
      </h2>
      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
            {TEXTS.basic.name} *
          </label>
          <input
            type="text"
            value={data.name}
            onChange={(e) => { onNameChange(e.target.value); }}
            className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
            {TEXTS.basic.description}
          </label>
          <textarea
            value={data.description}
            onChange={(e) => { onDescriptionChange(e.target.value); }}
            rows={3}
            className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white resize-none"
          />
        </div>

        <div className="flex items-center space-x-2">
          <input
            type="checkbox"
            id="isPublic"
            checked={data.isPublic}
            onChange={(e) => { onIsPublicChange(e.target.checked); }}
            className="rounded border-gray-300 dark:border-slate-600"
          />
          <label htmlFor="isPublic" className="text-sm text-gray-700 dark:text-slate-300">
            {TEXTS.basic.public}
          </label>
        </div>

        <div className="flex justify-end">
          <button
            onClick={handleSaveClick}
            disabled={isSaving}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            <Save className="h-4 w-4" />
            {isSaving ? TEXTS.basic.saving : TEXTS.basic.save}
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
  const handleSaveClick = useCallback(() => {
    onSave();
  }, [onSave]);

  return (
    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
        {TEXTS.memory.title}
      </h2>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              {TEXTS.memory.max_episodes}
            </label>
            <input
              type="number"
              value={data.maxEpisodes}
              onChange={(e) => { onMaxEpisodesChange(Number(e.target.value)); }}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              {TEXTS.memory.retention}
            </label>
            <input
              type="number"
              value={data.retentionDays}
              onChange={(e) => { onRetentionDaysChange(Number(e.target.value)); }}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
            />
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <input
            type="checkbox"
            id="autoRefresh"
            checked={data.autoRefresh}
            onChange={(e) => { onAutoRefreshChange(e.target.checked); }}
            className="rounded border-gray-300 dark:border-slate-600"
          />
          <label htmlFor="autoRefresh" className="text-sm text-gray-700 dark:text-slate-300">
            {TEXTS.memory.auto_refresh}
          </label>
        </div>

        {data.autoRefresh && (
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              {TEXTS.memory.interval}
            </label>
            <input
              type="number"
              value={data.refreshInterval}
              onChange={(e) => { onRefreshIntervalChange(Number(e.target.value)); }}
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
            {isSaving ? TEXTS.basic.saving : TEXTS.memory.save}
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
  const handleSaveClick = useCallback(() => {
    onSave();
  }, [onSave]);

  return (
    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
        {TEXTS.graph.title}
      </h2>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              {TEXTS.graph.max_nodes}
            </label>
            <input
              type="number"
              value={data.maxNodes}
              onChange={(e) => { onMaxNodesChange(Number(e.target.value)); }}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              {TEXTS.graph.max_edges}
            </label>
            <input
              type="number"
              value={data.maxEdges}
              onChange={(e) => { onMaxEdgesChange(Number(e.target.value)); }}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
            {TEXTS.graph.threshold}: {data.similarityThreshold}
          </label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={data.similarityThreshold}
            onChange={(e) => { onSimilarityThresholdChange(Number(e.target.value)); }}
            className="w-full"
          />
        </div>

        <div className="flex items-center space-x-2">
          <input
            type="checkbox"
            id="communityDetection"
            checked={data.communityDetection}
            onChange={(e) => { onCommunityDetectionChange(e.target.checked); }}
            className="rounded border-gray-300 dark:border-slate-600"
          />
          <label htmlFor="communityDetection" className="text-sm text-gray-700 dark:text-slate-300">
            Enable Community Detection
          </label>
        </div>

        <div className="flex justify-end">
          <button
            onClick={handleSaveClick}
            disabled={isSaving}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            <Save className="h-4 w-4" />
            {isSaving ? TEXTS.basic.saving : TEXTS.graph.save}
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
  const handleExport = useCallback(() => {
    onExportData();
  }, [onExportData]);

  const handleClearCache = useCallback(() => {
    onClearCache();
  }, [onClearCache]);

  const handleRebuild = useCallback(() => {
    onRebuildCommunities();
  }, [onRebuildCommunities]);

  return (
    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
        {TEXTS.advanced.title}
      </h2>
      <div className="space-y-4">
        <div className="flex items-center gap-4">
          <button
            onClick={handleExport}
            className="px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors flex items-center gap-2"
          >
            <Download className="h-4 w-4" />
            {TEXTS.advanced.export}
          </button>
          <button
            onClick={handleClearCache}
            className="px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors flex items-center gap-2"
          >
            <RefreshCw className="h-4 w-4" />
            {TEXTS.advanced.clear_cache}
          </button>
          <button
            onClick={handleRebuild}
            className="px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors flex items-center gap-2"
          >
            <RefreshCw className="h-4 w-4" />
            {TEXTS.advanced.rebuild}
          </button>
        </div>
      </div>
    </div>
  );
};
Advanced.displayName = 'ProjectSettings.Advanced';

// Danger Zone Sub-Component
const Danger: React.FC<ProjectSettingsDangerProps> = ({ projectName: _projectName, onDelete }) => {
  const handleDelete = useCallback(() => {
    onDelete();
  }, [onDelete]);

  return (
    <div className="bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800 p-6">
      <h2 className="text-lg font-semibold text-red-900 dark:text-red-300 mb-4">
        {TEXTS.danger.title}
      </h2>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-red-800 dark:text-red-300 mb-1">{TEXTS.danger.desc}</p>
          <p className="text-xs text-red-600 dark:text-red-400">{TEXTS.danger.warning}</p>
        </div>
        <button
          onClick={handleDelete}
          className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors flex items-center gap-2"
        >
          <Trash2 className="h-4 w-4" />
          {TEXTS.danger.delete}
        </button>
      </div>
    </div>
  );
};
Danger.displayName = 'ProjectSettings.Danger';

// NoProject Sub-Component
const NoProject: React.FC<ProjectSettingsNoProjectProps> = () => (
  <div className="p-8 text-center text-slate-500">
    <SettingsIcon className="h-12 w-12 mx-auto mb-3 opacity-50" />
    <p>{TEXTS.noProject}</p>
  </div>
);
NoProject.displayName = 'ProjectSettings.NoProject';

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
  Danger: typeof Danger;
  NoProject: typeof NoProject;
} = ({ className = '' }) => {
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

      if (currentProject.memory_rules) {
        setMaxEpisodes(currentProject.memory_rules.max_episodes || 100);
        setRetentionDays(currentProject.memory_rules.retention_days || 365);
        setAutoRefresh(currentProject.memory_rules.auto_refresh);
        setRefreshInterval(currentProject.memory_rules.refresh_interval || 24);
      }

      if (currentProject.graph_config) {
        setMaxNodes(currentProject.graph_config.max_nodes || 10000);
        setMaxEdges(currentProject.graph_config.max_edges || 50000);
        setSimilarityThreshold(currentProject.graph_config.similarity_threshold || 0.8);
        setCommunityDetection(currentProject.graph_config.community_detection);
      }
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
      setMessage({ type: 'success', text: TEXTS.messages.saved });
      setTimeout(() => {
        window.location.reload();
      }, 1000);
    } catch (error) {
      console.error('Failed to save settings:', error);
      const err = error as { response?: { data?: { detail?: string | undefined } | undefined } | undefined; message?: string | undefined };
      setMessage({
        type: 'error',
        text: `${TEXTS.messages.failed}: ${err.response?.data?.detail || err.message}`,
      });
    } finally {
      setIsSaving(false);
    }
  }, [currentProject, name, description, isPublic]);

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
      setMessage({ type: 'success', text: TEXTS.messages.saved });
    } catch (error) {
      console.error('Failed to save memory rules:', error);
      const err = error as { response?: { data?: { detail?: string | undefined } | undefined } | undefined; message?: string | undefined };
      setMessage({
        type: 'error',
        text: `${TEXTS.messages.failed}: ${err.response?.data?.detail || err.message}`,
      });
    } finally {
      setIsSaving(false);
    }
  }, [currentProject, maxEpisodes, retentionDays, autoRefresh, refreshInterval]);

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
      setMessage({ type: 'success', text: TEXTS.messages.saved });
    } catch (error) {
      console.error('Failed to save graph config:', error);
      const err = error as { response?: { data?: { detail?: string | undefined } | undefined } | undefined; message?: string | undefined };
      setMessage({
        type: 'error',
        text: `${TEXTS.messages.failed}: ${err.response?.data?.detail || err.message}`,
      });
    } finally {
      setIsSaving(false);
    }
  }, [currentProject, maxNodes, maxEdges, similarityThreshold, communityDetection]);

  const handleClearCache = useCallback(async () => {
    if (!currentProject) return;

    if (!window.confirm(TEXTS.advanced.confirm_clear)) {
      return;
    }

    setMessage(null);
    try {
      await api.post('/maintenance/refresh/incremental', {
        rebuild_communities: true,
      });
      setMessage({ type: 'success', text: 'Cache cleared successfully' });
    } catch (error) {
      console.error('Failed to clear cache:', error);
      setMessage({ type: 'error', text: 'Failed to clear cache' });
    }
  }, [currentProject]);

  const handleRebuildCommunities = useCallback(async () => {
    if (!currentProject) return;

    if (!window.confirm(TEXTS.advanced.confirm_rebuild)) {
      return;
    }

    setMessage(null);
    try {
      await api.post('/communities/rebuild');
      setMessage({ type: 'success', text: 'Community rebuild submitted' });
    } catch (error) {
      console.error('Failed to rebuild communities:', error);
      setMessage({ type: 'error', text: 'Failed to rebuild communities' });
    }
  }, [currentProject]);

  const handleExportData = useCallback(async () => {
    if (!currentProject) return;

    setMessage(null);
    try {
      const response = await api.post('/export', {
        tenant_id: currentProject.tenant_id,
        include_episodes: true,
        include_entities: true,
        include_relationships: true,
        include_communities: true,
      });

      const data = response as { data: unknown };
      const jsonString = JSON.stringify(data.data, null, 2);
      const blob = new Blob([jsonString], { type: 'application/json' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `project-${currentProject.id}-export-${new Date().toISOString().split('T')[0]}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);

      setMessage({ type: 'success', text: 'Data exported successfully' });
    } catch (error) {
      console.error('Failed to export data:', error);
      setMessage({ type: 'error', text: 'Failed to export data' });
    }
  }, [currentProject]);

  const handleDeleteProject = useCallback(async () => {
    if (!currentProject) return;

    const confirmText = prompt(TEXTS.danger.confirm_prompt);
    if (confirmText !== currentProject.name) {
      alert(TEXTS.danger.name_mismatch);
      return;
    }

    try {
      await projectAPI.delete(currentProject.tenant_id, currentProject.id);
      alert(TEXTS.danger.success);
      window.location.href = '/tenant';
    } catch (error) {
      console.error('Failed to delete project:', error);
      alert(TEXTS.danger.fail);
    }
  }, [currentProject]);

  const clearMessage = useCallback(() => {
    setMessage(null);
  }, []);

  // No project state
  if (!currentProject) {
    return <NoProject />;
  }

  return (
    <div className={`p-8 space-y-6 ${className}`}>
      <Header title={TEXTS.title} />
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
ProjectSettings.Danger = Danger;
ProjectSettings.NoProject = NoProject;

export default ProjectSettings;
