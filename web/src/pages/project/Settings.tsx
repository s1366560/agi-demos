import React, { useState, useEffect, useCallback } from 'react';
import { Settings as SettingsIcon, Save, Trash2, Download, RefreshCw, AlertCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useProjectStore } from '../../stores/project';
import api, { projectAPI } from '../../services/api';

export const ProjectSettings: React.FC = () => {
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

    useEffect(() => {
        if (currentProject) {
            setName(currentProject.name || '');
            setDescription(currentProject.description || '');
            setIsPublic(currentProject.is_public || false);

            // Load memory rules
            if (currentProject.memory_rules) {
                setMaxEpisodes(currentProject.memory_rules.max_episodes || 100);
                setRetentionDays(currentProject.memory_rules.retention_days || 365);
                setAutoRefresh(currentProject.memory_rules.auto_refresh !== false);
                setRefreshInterval(currentProject.memory_rules.refresh_interval || 24);
            }

            // Load graph config
            if (currentProject.graph_config) {
                setMaxNodes(currentProject.graph_config.max_nodes || 10000);
                setMaxEdges(currentProject.graph_config.max_edges || 50000);
                setSimilarityThreshold(currentProject.graph_config.similarity_threshold || 0.8);
                setCommunityDetection(currentProject.graph_config.community_detection !== false);
            }
        }
    }, [currentProject]);

    const handleSaveBasicSettings = useCallback(async () => {
        if (!currentProject) return;

        setIsSaving(true);
        setMessage(null);

        try {
            await projectAPI.update(
                currentProject.tenant_id,
                currentProject.id,
                { name, description, is_public: isPublic }
            );

            setMessage({ type: 'success', text: t('project.settings.messages.saved') });

            // Reload project data
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        } catch (error: unknown) {
            console.error('Failed to save settings:', error);
            const err = error as { response?: { data?: { detail?: string } }; message?: string };
            setMessage({ type: 'error', text: t('project.settings.messages.failed', { error: err.response?.data?.detail || err.message }) });
        } finally {
            setIsSaving(false);
        }
    }, [currentProject, name, description, isPublic, t]);

    const handleSaveMemoryRules = useCallback(async () => {
        if (!currentProject) return;

        setIsSaving(true);
        setMessage(null);

        try {
            await projectAPI.update(
                currentProject.tenant_id,
                currentProject.id,
                {
                    memory_rules: {
                        max_episodes: maxEpisodes,
                        retention_days: retentionDays,
                        auto_refresh: autoRefresh,
                        refresh_interval: refreshInterval
                    }
                }
            );

            setMessage({ type: 'success', text: t('project.settings.messages.saved') });
        } catch (err: unknown) {
            console.error('Failed to save memory rules:', err);
            const error = err as { response?: { data?: { detail?: string } }; message?: string };
            setMessage({ type: 'error', text: t('project.settings.messages.failed', { error: error.response?.data?.detail || error.message }) });
        } finally {
            setIsSaving(false);
        }
    }, [currentProject, maxEpisodes, retentionDays, autoRefresh, refreshInterval, t]);

    const handleSaveGraphConfig = useCallback(async () => {
        if (!currentProject) return;

        setIsSaving(true);
        setMessage(null);

        try {
            await projectAPI.update(
                currentProject.tenant_id,
                currentProject.id,
                {
                    graph_config: {
                        max_nodes: maxNodes,
                        max_edges: maxEdges,
                        similarity_threshold: similarityThreshold,
                        community_detection: communityDetection
                    }
                }
            );

            setMessage({ type: 'success', text: t('project.settings.messages.saved') });
        } catch (err: unknown) {
            console.error('Failed to save graph config:', err);
            const error = err as { response?: { data?: { detail?: string } }; message?: string };
            setMessage({ type: 'error', text: t('project.settings.messages.failed', { error: error.response?.data?.detail || error.message }) });
        } finally {
            setIsSaving(false);
        }
    }, [currentProject, maxNodes, maxEdges, similarityThreshold, communityDetection, t]);

    const handleClearCache = useCallback(async () => {
        if (!currentProject) return;

        if (!window.confirm(t('project.settings.advanced.confirm_clear'))) {
            return;
        }

        setMessage(null);
        try {
            // Use incremental refresh which can rebuild communities
            // Note: httpClient already has baseURL='/api/v1', so we don't prefix it here
            await api.post('/maintenance/refresh/incremental', {
                rebuild_communities: true
            });
            setMessage({ type: 'success', text: t('project.settings.messages.cache_cleared') });
        } catch (error) {
            console.error('Failed to clear cache:', error);
            setMessage({ type: 'error', text: t('project.settings.messages.cache_fail') });
        }
    }, [currentProject, t]);

    const handleRebuildCommunities = useCallback(async () => {
        if (!currentProject) return;

        if (!window.confirm(t('project.settings.advanced.confirm_rebuild'))) {
            return;
        }

        setMessage(null);
        try {
            await api.post('/communities/rebuild');
            setMessage({ type: 'success', text: t('project.settings.messages.rebuild_submitted') });
        } catch (error) {
            console.error('Failed to rebuild communities:', error);
            setMessage({ type: 'error', text: t('project.settings.messages.rebuild_fail') });
        }
    }, [currentProject, t]);

    const handleExportData = useCallback(async () => {
        if (!currentProject) return;

        setMessage(null);
        try {
            const response = await api.post('/export', {
                tenant_id: currentProject.tenant_id,
                include_episodes: true,
                include_entities: true,
                include_relationships: true,
                include_communities: true
            });

            // Create download link for JSON data
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

            setMessage({ type: 'success', text: t('project.settings.messages.export_success') });
        } catch (error) {
            console.error('Failed to export data:', error);
            setMessage({ type: 'error', text: t('project.settings.messages.export_fail') });
        }
    }, [currentProject, t]);

    const handleDeleteProject = useCallback(async () => {
        if (!currentProject) return;

        const confirmText = prompt(t('project.settings.danger.confirm_prompt'));
        if (confirmText !== currentProject.name) {
            alert(t('project.settings.danger.name_mismatch'));
            return;
        }

        try {
            await projectAPI.delete(currentProject.tenant_id, currentProject.id);
            alert(t('project.settings.danger.success'));
            window.location.href = '/tenant';
        } catch (error) {
            console.error('Failed to delete project:', error);
            alert(t('project.settings.danger.fail'));
        }
    }, [currentProject, t]);

    if (!currentProject) {
        return (
            <div className="p-8 text-center text-slate-500">
                <SettingsIcon className="h-12 w-12 mx-auto mb-3 opacity-50" />
                <p>{t('project.settings.no_project')}</p>
            </div>
        );
    }

    return (
        <div className="p-8 space-y-6">
            <div className="flex items-center space-x-2 mb-6">
                <SettingsIcon className="h-6 w-6 text-gray-600 dark:text-slate-400" />
                <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">{t('project.settings.title')}</h1>
            </div>

            {/* Message */}
            {message && (
                <div className={`p-4 rounded-md ${
                    message.type === 'success'
                        ? 'bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-300'
                        : 'bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-300'
                }`}>
                    <div className="flex items-center gap-2">
                        <AlertCircle className="h-4 w-4" />
                        {message.text}
                    </div>
                </div>
            )}

            {/* Basic Settings */}
            <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">{t('project.settings.basic.title')}</h2>
                <div className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                            {t('project.settings.basic.name')} *
                        </label>
                        <input
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                            {t('project.settings.basic.description')}
                        </label>
                        <textarea
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            rows={3}
                            className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white resize-none"
                        />
                    </div>

                    <div className="flex items-center space-x-2">
                        <input
                            type="checkbox"
                            id="isPublic"
                            checked={isPublic}
                            onChange={(e) => setIsPublic(e.target.checked)}
                            className="rounded border-gray-300 dark:border-slate-600"
                        />
                        <label htmlFor="isPublic" className="text-sm text-gray-700 dark:text-slate-300">
                            {t('project.settings.basic.public')}
                        </label>
                    </div>

                    <div className="flex justify-end">
                        <button
                            onClick={handleSaveBasicSettings}
                            disabled={isSaving}
                            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 flex items-center gap-2"
                        >
                            <Save className="h-4 w-4" />
                            {isSaving ? t('project.settings.basic.saving') : t('project.settings.basic.save')}
                        </button>
                    </div>
                </div>
            </div>

            {/* Memory Rules */}
            <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">{t('project.settings.memory.title')}</h2>
                <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                                {t('project.settings.memory.max_episodes')}
                            </label>
                            <input
                                type="number"
                                value={maxEpisodes}
                                onChange={(e) => setMaxEpisodes(Number(e.target.value))}
                                className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                                {t('project.settings.memory.retention')}
                            </label>
                            <input
                                type="number"
                                value={retentionDays}
                                onChange={(e) => setRetentionDays(Number(e.target.value))}
                                className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
                            />
                        </div>
                    </div>

                    <div className="flex items-center space-x-2">
                        <input
                            type="checkbox"
                            id="autoRefresh"
                            checked={autoRefresh}
                            onChange={(e) => setAutoRefresh(e.target.checked)}
                            className="rounded border-gray-300 dark:border-slate-600"
                        />
                        <label htmlFor="autoRefresh" className="text-sm text-gray-700 dark:text-slate-300">
                            {t('project.settings.memory.auto_refresh')}
                        </label>
                    </div>

                    {autoRefresh && (
                        <div>
                            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                                {t('project.settings.memory.interval')}
                            </label>
                            <input
                                type="number"
                                value={refreshInterval}
                                onChange={(e) => setRefreshInterval(Number(e.target.value))}
                                className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
                            />
                        </div>
                    )}

                    <div className="flex justify-end">
                        <button
                            onClick={handleSaveMemoryRules}
                            disabled={isSaving}
                            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 flex items-center gap-2"
                        >
                            <Save className="h-4 w-4" />
                            {isSaving ? t('project.settings.basic.saving') : t('project.settings.memory.save')}
                        </button>
                    </div>
                </div>
            </div>

            {/* Graph Configuration */}
            <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">{t('project.settings.graph.title')}</h2>
                <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                                {t('project.settings.graph.max_nodes')}
                            </label>
                            <input
                                type="number"
                                value={maxNodes}
                                onChange={(e) => setMaxNodes(Number(e.target.value))}
                                className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                                {t('project.settings.graph.max_edges')}
                            </label>
                            <input
                                type="number"
                                value={maxEdges}
                                onChange={(e) => setMaxEdges(Number(e.target.value))}
                                className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
                            />
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                            {t('project.settings.graph.threshold', { value: similarityThreshold })}
                        </label>
                        <input
                            type="range"
                            min="0"
                            max="1"
                            step="0.05"
                            value={similarityThreshold}
                            onChange={(e) => setSimilarityThreshold(Number(e.target.value))}
                            className="w-full"
                        />
                    </div>

                    <div className="flex items-center space-x-2">
                        <input
                            type="checkbox"
                            id="communityDetection"
                            checked={communityDetection}
                            onChange={(e) => setCommunityDetection(e.target.checked)}
                            className="rounded border-gray-300 dark:border-slate-600"
                        />
                        <label htmlFor="communityDetection" className="text-sm text-gray-700 dark:text-slate-300">
                            启用社区检测
                        </label>
                    </div>

                    <div className="flex justify-end">
                        <button
                            onClick={handleSaveGraphConfig}
                            disabled={isSaving}
                            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 flex items-center gap-2"
                        >
                            <Save className="h-4 w-4" />
                            {isSaving ? t('project.settings.basic.saving') : t('project.settings.graph.save')}
                        </button>
                    </div>
                </div>
            </div>

            {/* Advanced Settings */}
            <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">{t('project.settings.advanced.title')}</h2>
                <div className="space-y-4">
                    <div className="flex items-center gap-4">
                        <button
                            onClick={handleExportData}
                            className="px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors flex items-center gap-2"
                        >
                            <Download className="h-4 w-4" />
                            {t('project.settings.advanced.export')}
                        </button>
                        <button
                            onClick={handleClearCache}
                            className="px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors flex items-center gap-2"
                        >
                            <RefreshCw className="h-4 w-4" />
                            {t('project.settings.advanced.clear_cache')}
                        </button>
                        <button
                            onClick={handleRebuildCommunities}
                            className="px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors flex items-center gap-2"
                        >
                            <RefreshCw className="h-4 w-4" />
                            {t('project.settings.advanced.rebuild')}
                        </button>
                    </div>
                </div>
            </div>

            {/* Danger Zone */}
            <div className="bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800 p-6">
                <h2 className="text-lg font-semibold text-red-900 dark:text-red-300 mb-4">{t('project.settings.danger.title')}</h2>
                <div className="flex items-center justify-between">
                    <div>
                        <p className="text-sm text-red-800 dark:text-red-300 mb-1">
                            {t('project.settings.danger.desc')}
                        </p>
                        <p className="text-xs text-red-600 dark:text-red-400">{t('project.settings.danger.warning')}</p>
                    </div>
                    <button
                        onClick={handleDeleteProject}
                        className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors flex items-center gap-2"
                    >
                        <Trash2 className="h-4 w-4" />
                        {t('project.settings.danger.delete')}
                    </button>
                </div>
            </div>
        </div>
    );
};
