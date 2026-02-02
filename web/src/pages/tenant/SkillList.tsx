/**
 * Skill List Page
 *
 * Management page for Skills with CRUD operations and filtering/search functionality.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLazyMessage, LazyPopconfirm, LazySelect, LazyEmpty, LazySpin } from '@/components/ui/lazyAntd';
import { Input } from 'antd';
import {
  useSkillStore,
  useSkillLoading,
  useSkillError,
  useActiveSkillsCount,
  useAverageSuccessRate,
  useTotalUsageCount,
  useSkillTotal,
} from '../../stores/skill';
import { SkillModal } from '../../components/skill/SkillModal';
import type { SkillResponse } from '../../types/agent';

const { Search } = Input;

export const SkillList: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'disabled' | 'deprecated'>('all');
  const [triggerTypeFilter, setTriggerTypeFilter] = useState<'all' | 'keyword' | 'semantic' | 'hybrid'>('all');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<SkillResponse | null>(null);

  // Store hooks
  const { skills } = useSkillStore();
  const isLoading = useSkillLoading();
  const error = useSkillError();
  const activeCount = useActiveSkillsCount();
  const avgSuccessRate = useAverageSuccessRate();
  const totalUsageCount = useTotalUsageCount();
  const total = useSkillTotal();

  // Filter skills locally with useMemo to prevent infinite loops
  const filteredSkills = React.useMemo(() => {
    return skills.filter((skill) => {
      // Search filter
      if (search) {
        const searchLower = search.toLowerCase();
        const matchesName = skill.name.toLowerCase().includes(searchLower);
        const matchesDescription = skill.description.toLowerCase().includes(searchLower);
        if (!matchesName && !matchesDescription) {
          return false;
        }
      }

      // Status filter
      if (statusFilter !== 'all' && skill.status !== statusFilter) {
        return false;
      }

      // Trigger type filter
      if (triggerTypeFilter !== 'all' && skill.trigger_type !== triggerTypeFilter) {
        return false;
      }

      return true;
    });
  }, [skills, search, statusFilter, triggerTypeFilter]);

  const {
    listSkills,
    deleteSkill,
    updateSkillStatus,
    clearError,
  } = useSkillStore();

  // Load data on mount
  useEffect(() => {
    listSkills();
  }, [listSkills]);

  // Clear error on unmount
  useEffect(() => {
    return () => clearError();
  }, [clearError]);

  // Show error message
  useEffect(() => {
    if (error) {
      message?.error(error);
    }
  }, [error]);

  // Handlers
  const handleCreate = useCallback(() => {
    setEditingSkill(null);
    setIsModalOpen(true);
  }, []);

  const handleEdit = useCallback((skill: SkillResponse) => {
    setEditingSkill(skill);
    setIsModalOpen(true);
  }, []);

  const handleStatusChange = useCallback(async (id: string, status: 'active' | 'disabled' | 'deprecated') => {
    try {
      await updateSkillStatus(id, status);
      message?.success(t('tenant.skills.statusUpdateSuccess'));
    } catch {
      // Error handled by store
    }
  }, [updateSkillStatus, t]);

  const handleDelete = useCallback(async (id: string) => {
    try {
      await deleteSkill(id);
      message?.success(t('tenant.skills.deleteSuccess'));
    } catch {
      // Error handled by store
    }
  }, [deleteSkill, t]);

  const handleModalClose = useCallback(() => {
    setIsModalOpen(false);
    setEditingSkill(null);
  }, []);

  const handleModalSuccess = useCallback(() => {
    setIsModalOpen(false);
    setEditingSkill(null);
    listSkills();
  }, [listSkills]);

  const handleRefresh = useCallback(() => {
    listSkills();
  }, [listSkills]);

  // Status badge component
  const StatusBadge = ({ status }: { status: 'active' | 'disabled' | 'deprecated' }) => {
    const config = {
      active: { bg: 'bg-green-100 dark:bg-green-900/30', text: 'text-green-800 dark:text-green-300', dot: 'bg-green-500' },
      disabled: { bg: 'bg-slate-100 dark:bg-slate-700', text: 'text-slate-800 dark:text-slate-300', dot: 'bg-slate-400' },
      deprecated: { bg: 'bg-orange-100 dark:bg-orange-900/30', text: 'text-orange-800 dark:text-orange-300', dot: 'bg-orange-500' },
    };
    const { bg, text, dot } = config[status];
    return (
      <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${bg} ${text}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${dot}`}></span>
        {t(`common.status.${status}`)}
      </span>
    );
  };

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {t('tenant.skills.title')}
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            {t('tenant.skills.subtitle')}
          </p>
        </div>
        <button
          onClick={handleCreate}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
        >
          <span className="material-symbols-outlined text-lg">add</span>
          {t('tenant.skills.createNew')}
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">{t('tenant.skills.stats.total')}</p>
              <p className="text-2xl font-bold text-slate-900 dark:text-white mt-1">{total}</p>
            </div>
            <span className="material-symbols-outlined text-4xl text-primary-500">school</span>
          </div>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">{t('tenant.skills.stats.active')}</p>
              <p className="text-2xl font-bold text-green-600 dark:text-green-400 mt-1">{activeCount}</p>
            </div>
            <span className="material-symbols-outlined text-4xl text-green-500">check_circle</span>
          </div>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">{t('tenant.skills.stats.successRate')}</p>
              <p className="text-2xl font-bold text-blue-600 dark:text-blue-400 mt-1">
                {(avgSuccessRate * 100).toFixed(1)}%
              </p>
            </div>
            <span className="material-symbols-outlined text-4xl text-blue-500">trending_up</span>
          </div>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">{t('tenant.skills.stats.totalUsage')}</p>
              <p className="text-2xl font-bold text-purple-600 dark:text-purple-400 mt-1">{totalUsageCount}</p>
            </div>
            <span className="material-symbols-outlined text-4xl text-purple-500">bar_chart</span>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1">
            <Search
              placeholder={t('tenant.skills.searchPlaceholder')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              allowClear
            />
          </div>
          <LazySelect
            value={statusFilter}
            onChange={setStatusFilter}
            className="w-full sm:w-40"
            options={[
              { label: t('common.status.all'), value: 'all' },
              { label: t('common.status.active'), value: 'active' },
              { label: t('common.status.disabled'), value: 'disabled' },
              { label: t('common.status.deprecated'), value: 'deprecated' },
            ]}
          />
          <LazySelect
            value={triggerTypeFilter}
            onChange={setTriggerTypeFilter}
            className="w-full sm:w-40"
            options={[
              { label: t('tenant.skills.triggerTypes.all'), value: 'all' },
              { label: t('tenant.skills.triggerTypes.keyword'), value: 'keyword' },
              { label: t('tenant.skills.triggerTypes.semantic'), value: 'semantic' },
              { label: t('tenant.skills.triggerTypes.hybrid'), value: 'hybrid' },
            ]}
          />
          <button
            onClick={handleRefresh}
            className="inline-flex items-center justify-center px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700"
          >
            <span className="material-symbols-outlined">refresh</span>
          </button>
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <LazySpin size="large" />
        </div>
      ) : skills.length === 0 ? (
        <LazyEmpty
          description={t('tenant.skills.empty')}
          className="py-12"
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredSkills.map((skill) => (
            <div
              key={skill.id}
              className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700 hover:shadow-lg transition-shadow"
            >
              {/* Header */}
              <div className="flex items-start justify-between mb-4">
                <div className="flex-1">
                  <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-1">
                    {skill.name}
                  </h3>
                  <StatusBadge status={skill.status} />
                </div>
              </div>

              {/* Description */}
              <p className="text-sm text-slate-600 dark:text-slate-400 mb-4 line-clamp-2">
                {skill.description}
              </p>

              {/* Trigger Type */}
              <div className="mb-4">
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {t('tenant.skills.triggerType')}: 
                </span>
                <span className="ml-2 text-xs font-medium text-primary-600 dark:text-primary-400">
                  {skill.trigger_type}
                </span>
              </div>

              {/* Trigger Patterns */}
              <div className="mb-4">
                <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
                  {t('tenant.skills.triggerPatterns')} ({skill.trigger_patterns.length})
                </p>
                <div className="flex flex-wrap gap-1">
                  {skill.trigger_patterns.slice(0, 4).map((pattern, idx) => (
                    <span
                      key={idx}
                      className="inline-flex px-2 py-0.5 bg-slate-100 dark:bg-slate-700 text-xs text-slate-700 dark:text-slate-300 rounded"
                    >
                      {pattern.pattern}
                    </span>
                  ))}
                  {skill.trigger_patterns.length > 4 && (
                    <span className="inline-flex px-2 py-0.5 bg-slate-100 dark:bg-slate-700 text-xs text-slate-700 dark:text-slate-300 rounded">
                      +{skill.trigger_patterns.length - 4}
                    </span>
                  )}
                </div>
              </div>

              {/* Tools */}
              <div className="mb-4">
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t('tenant.skills.tools')}: {skill.tools.length}
                </p>
              </div>

              {/* Stats */}
              <div className="grid grid-cols-3 gap-4 mb-4 pt-4 border-t border-slate-200 dark:border-slate-700">
                <div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{t('common.stats.usage')}</p>
                  <p className="text-sm font-semibold text-slate-900 dark:text-white">{skill.usage_count}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{t('common.stats.successRate')}</p>
                  <p className="text-sm font-semibold text-slate-900 dark:text-white">
                    {(skill.success_rate * 100).toFixed(0)}%
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{t('common.stats.success')}</p>
                  <p className="text-sm font-semibold text-green-600 dark:text-green-400">
                    {skill.success_count}
                  </p>
                </div>
              </div>

              {/* Actions */}
              <div className="flex items-center justify-between pt-4 border-t border-slate-200 dark:border-slate-700">
                <LazySelect
                  value={skill.status}
                  onChange={(status: any) => handleStatusChange(skill.id, status)}
                  className="w-32"
                  size="small"
                  options={[
                    { label: t('common.status.active'), value: 'active' },
                    { label: t('common.status.disabled'), value: 'disabled' },
                    { label: t('common.status.deprecated'), value: 'deprecated' },
                  ]}
                />
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleEdit(skill)}
                    className="p-2 text-slate-600 dark:text-slate-400 hover:text-primary-600 dark:hover:text-primary-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700"
                  >
                    <span className="material-symbols-outlined text-lg">edit</span>
                  </button>
                  <LazyPopconfirm
                    title={t('tenant.skills.deleteConfirm')}
                    onConfirm={() => handleDelete(skill.id)}
                    okText={t('common.confirm')}
                    cancelText={t('common.cancel')}
                  >
                    <button className="p-2 text-slate-600 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700">
                      <span className="material-symbols-outlined text-lg">delete</span>
                    </button>
                  </LazyPopconfirm>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal */}
      {isModalOpen && (
        <SkillModal
          isOpen={isModalOpen}
          skill={editingSkill}
          onClose={handleModalClose}
          onSuccess={handleModalSuccess}
        />
      )}
    </div>
  );
};

export default SkillList;
