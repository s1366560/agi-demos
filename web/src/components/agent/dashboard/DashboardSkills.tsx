/**
 * Dashboard Skills Component
 *
 * Displays list of available skills, skill trigger patterns,
 * and skill status (active/disabled).
 */

import { memo, useEffect, useMemo, useState, useCallback } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { CheckCircle, Puzzle, RefreshCw, Search, XCircle, Zap } from 'lucide-react';

import {
  useSkills,
  useSkillLoading,
  useSkillStore,
  useActiveSkillsCount,
  useTotalUsageCount,
} from '../../../stores/skill';

import type { SkillResponse } from '../../../types/agent';

// ============================================================================
// Skill Card Component
// ============================================================================

interface SkillCardProps {
  skill: SkillResponse;
}

const SkillCard: FC<SkillCardProps> = memo(({ skill }) => {
  const isActive = skill.status === 'active';

  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-4 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div
            className={`p-2 rounded-lg ${
              isActive
                ? 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400'
                : 'bg-slate-100 dark:bg-slate-700 text-slate-400'
            }`}
          >
            <Puzzle size={18} />
          </div>
          <div>
            <h4 className="font-medium text-sm text-slate-900 dark:text-white">{skill.name}</h4>
            <p className="text-xs text-slate-500 dark:text-slate-400">{skill.trigger_type}</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {isActive ? (
            <CheckCircle size={14} className="text-green-500" />
          ) : (
            <XCircle size={14} className="text-slate-400" />
          )}
        </div>
      </div>

      <p className="text-xs text-slate-500 dark:text-slate-400 mb-3 line-clamp-2">
        {skill.description}
      </p>

      {/* Trigger Patterns */}
      <div className="mb-3">
        <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
          Trigger Patterns
        </p>
        <div className="flex flex-wrap gap-1">
          {skill.trigger_patterns.slice(0, 3).map((pattern, idx) => (
            <span
              key={idx}
              className="px-2 py-0.5 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 text-2xs rounded"
            >
              {pattern.pattern}
            </span>
          ))}
          {skill.trigger_patterns.length > 3 && (
            <span className="px-2 py-0.5 bg-slate-100 dark:bg-slate-700 text-slate-400 text-2xs rounded">
              +{skill.trigger_patterns.length - 3} more
            </span>
          )}
        </div>
      </div>

      {/* Tools */}
      <div className="mb-3">
        <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">Tools</p>
        <div className="flex flex-wrap gap-1">
          {skill.tools.slice(0, 4).map((tool, idx) => (
            <span
              key={idx}
              className="px-2 py-0.5 bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 text-2xs rounded"
            >
              {tool}
            </span>
          ))}
          {skill.tools.length > 4 && (
            <span className="px-2 py-0.5 bg-blue-50 dark:bg-blue-900/20 text-blue-400 text-2xs rounded">
              +{skill.tools.length - 4}
            </span>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className="flex items-center justify-between text-xs text-slate-400 dark:text-slate-500 pt-2 border-t border-slate-100 dark:border-slate-700">
        <span className="flex items-center gap-1">
          <Zap size={12} />
          {skill.usage_count} uses
        </span>
        <span className="flex items-center gap-1">{skill.success_rate}% success</span>
      </div>
    </div>
  );
});
SkillCard.displayName = 'SkillCard';

// ============================================================================
// Dashboard Skills Component
// ============================================================================

export const DashboardSkills: FC = memo(() => {
  const { t } = useTranslation();

  const skills = useSkills();
  const isLoading = useSkillLoading();
  const listSkills = useSkillStore((state) => state.listSkills);
  const activeCount = useActiveSkillsCount();
  const totalUsage = useTotalUsageCount();

  const [search, setSearch] = useState('');

  useEffect(() => {
    void listSkills({});
  }, [listSkills]);

  const filteredSkills = useMemo(() => {
    if (!search) return skills;
    const lower = search.toLowerCase();
    return skills.filter(
      (skill) =>
        skill.name.toLowerCase().includes(lower) || skill.description.toLowerCase().includes(lower)
    );
  }, [skills, search]);

  const handleRefresh = useCallback(() => {
    void listSkills({});
  }, [listSkills]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-white">
            {t('tenant.dashboard.skills.title', 'Skills')}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.skills.subtitle', 'Manage declarative tool compositions')}
          </p>
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={isLoading}
          className="inline-flex items-center gap-2 px-3 py-1.5 text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-colors"
        >
          <RefreshCw
            size={14}
            className={isLoading ? 'animate-spin motion-reduce:animate-none' : ''}
          />
          {t('common.refresh', 'Refresh')}
        </button>
      </div>

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
        <input
          type="text"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
          placeholder={t('tenant.dashboard.skills.searchPlaceholder', 'Search skills...')}
          className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-primary/30 focus:border-primary outline-none"
        />
      </div>

      {/* Stats Summary */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.skills.totalSkills', 'Total Skills')}
          </p>
          <p className="mt-1 text-xl font-bold text-slate-900 dark:text-white">{skills.length}</p>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.skills.activeSkills', 'Active')}
          </p>
          <p className="mt-1 text-xl font-bold text-green-600 dark:text-green-400">{activeCount}</p>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.skills.totalUsage', 'Total Usage')}
          </p>
          <p className="mt-1 text-xl font-bold text-slate-900 dark:text-white">
            {totalUsage.toLocaleString()}
          </p>
        </div>
      </div>

      {/* Skills Grid */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin motion-reduce:animate-none" />
        </div>
      ) : filteredSkills.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-slate-500 dark:text-slate-400">
          <Puzzle size={48} className="mb-4 text-slate-300 dark:text-slate-600" />
          <p className="text-lg font-medium">
            {t('tenant.dashboard.skills.noSkills', 'No skills found')}
          </p>
          <p className="text-sm mt-1">
            {search
              ? t('tenant.dashboard.skills.noResults', 'Try a different search term')
              : t('tenant.dashboard.skills.emptyHint', 'Create skills to get started')}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredSkills.map((skill) => (
            <SkillCard key={skill.id} skill={skill} />
          ))}
        </div>
      )}
    </div>
  );
});
DashboardSkills.displayName = 'DashboardSkills';

export default DashboardSkills;
