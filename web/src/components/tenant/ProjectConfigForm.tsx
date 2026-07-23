import React from 'react';

import { useTranslation } from 'react-i18next';

import { Brain, Network } from 'lucide-react';

import { NumberInput } from '@/components/tenant/NumberInput';

import type { GraphConfig, MemoryRulesConfig } from '@/types/memory';

interface ProjectConfigFormProps {
  /** Prefix used to keep input ids unique when several forms share a page. */
  idPrefix: string;
  memoryRules: MemoryRulesConfig;
  graphConfig: GraphConfig;
  onMemoryRulesChange: (next: MemoryRulesConfig) => void;
  onGraphConfigChange: (next: GraphConfig) => void;
}

const toggleClass =
  'w-11 h-6 bg-slate-200 peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-primary/20 dark:peer-focus-visible:ring-primary/40 rounded-full peer dark:bg-slate-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[""] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-transform dark:border-gray-600 peer-checked:bg-primary';

/**
 * Shared Memory Rules + Graph Configuration cards used by both the
 * NewProject and EditProject pages.
 */
export const ProjectConfigForm: React.FC<ProjectConfigFormProps> = ({
  idPrefix,
  memoryRules,
  graphConfig,
  onMemoryRulesChange,
  onGraphConfigChange,
}) => {
  const { t } = useTranslation();

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Memory Rules */}
      <div className="bg-surface-light dark:bg-surface-dark border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm h-full">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-purple-50 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400 rounded-lg">
            <Brain size={16} />
          </div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-white">
            {t('tenant.newProject.memoryRules')}
          </h2>
        </div>

        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label
                htmlFor={`${idPrefix}-max-episodes`}
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
              >
                {t('tenant.newProject.maxEpisodes')}
              </label>
              <NumberInput
                id={`${idPrefix}-max-episodes`}
                name="max_episodes"
                min={100}
                max={10000}
                value={memoryRules.max_episodes}
                onCommit={(value) => {
                  onMemoryRulesChange({ ...memoryRules, max_episodes: value });
                }}
              />
            </div>
            <div>
              <label
                htmlFor={`${idPrefix}-retention-days`}
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
              >
                {t('tenant.newProject.retentionDays')}
              </label>
              <NumberInput
                id={`${idPrefix}-retention-days`}
                name="retention_days"
                min={1}
                max={365}
                value={memoryRules.retention_days}
                onCommit={(value) => {
                  onMemoryRulesChange({ ...memoryRules, retention_days: value });
                }}
              />
            </div>
          </div>

          <div>
            <label
              htmlFor={`${idPrefix}-refresh-interval`}
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
            >
              {t('tenant.newProject.refreshInterval')}
            </label>
            <NumberInput
              id={`${idPrefix}-refresh-interval`}
              name="refresh_interval"
              min={1}
              max={168}
              value={memoryRules.refresh_interval}
              onCommit={(value) => {
                onMemoryRulesChange({ ...memoryRules, refresh_interval: value });
              }}
            />
          </div>

          <div className="flex items-center gap-3 pt-2">
            <label
              htmlFor={`${idPrefix}-auto-refresh`}
              className="relative inline-flex items-center cursor-pointer"
            >
              <input
                id={`${idPrefix}-auto-refresh`}
                name="auto_refresh"
                type="checkbox"
                checked={memoryRules.auto_refresh}
                onChange={(e) => {
                  onMemoryRulesChange({ ...memoryRules, auto_refresh: e.target.checked });
                }}
                className="sr-only peer"
              />
              <div className={toggleClass}></div>
              <span className="ml-3 text-sm font-medium text-slate-700 dark:text-slate-300">
                {t('tenant.newProject.enableAutoRefresh')}
              </span>
            </label>
          </div>
        </div>
      </div>

      {/* Graph Configuration */}
      <div className="bg-surface-light dark:bg-surface-dark border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm h-full">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400 rounded-lg">
            <Network size={16} />
          </div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-white">
            {t('tenant.newProject.graphConfig')}
          </h2>
        </div>

        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label
                htmlFor={`${idPrefix}-max-nodes`}
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
              >
                {t('tenant.newProject.maxNodes')}
              </label>
              <NumberInput
                id={`${idPrefix}-max-nodes`}
                name="max_nodes"
                min={100}
                value={graphConfig.max_nodes}
                onCommit={(value) => {
                  onGraphConfigChange({ ...graphConfig, max_nodes: value });
                }}
              />
            </div>
            <div>
              <label
                htmlFor={`${idPrefix}-max-edges`}
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
              >
                {t('tenant.newProject.maxEdges')}
              </label>
              <NumberInput
                id={`${idPrefix}-max-edges`}
                name="max_edges"
                min={100}
                value={graphConfig.max_edges}
                onCommit={(value) => {
                  onGraphConfigChange({ ...graphConfig, max_edges: value });
                }}
              />
            </div>
          </div>

          <div>
            <div className="flex justify-between items-center mb-2">
              <label
                htmlFor={`${idPrefix}-similarity-threshold`}
                className="block text-sm font-medium text-slate-700 dark:text-slate-300"
              >
                {t('tenant.newProject.similarityThreshold')}
              </label>
              <span className="text-xs font-mono bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded text-slate-600 dark:text-slate-300">
                {graphConfig.similarity_threshold}
              </span>
            </div>
            <input
              id={`${idPrefix}-similarity-threshold`}
              name="similarity_threshold"
              type="range"
              min="0.1"
              max="1.0"
              step="0.1"
              value={graphConfig.similarity_threshold}
              onChange={(e) => {
                onGraphConfigChange({
                  ...graphConfig,
                  similarity_threshold: parseFloat(e.target.value),
                });
              }}
              className="w-full h-2 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-primary"
            />
            <div className="flex justify-between text-xs text-slate-400 mt-1">
              <span>{t('tenant.newProject.loose', { defaultValue: 'Loose (0.1)' })}</span>
              <span>{t('tenant.newProject.strict', { defaultValue: 'Strict (1.0)' })}</span>
            </div>
          </div>

          <div className="flex items-center gap-3 pt-2">
            <label
              htmlFor={`${idPrefix}-community-detection`}
              className="relative inline-flex items-center cursor-pointer"
            >
              <input
                id={`${idPrefix}-community-detection`}
                name="community_detection"
                type="checkbox"
                checked={graphConfig.community_detection}
                onChange={(e) => {
                  onGraphConfigChange({ ...graphConfig, community_detection: e.target.checked });
                }}
                className="sr-only peer"
              />
              <div className={toggleClass}></div>
              <span className="ml-3 text-sm font-medium text-slate-700 dark:text-slate-300">
                {t('tenant.newProject.enableCommunityDetection')}
              </span>
            </label>
          </div>
        </div>
      </div>
    </div>
  );
};
