/**
 * Skill List Page
 *
 * Management page for Skills with CRUD operations and filtering/search functionality.
 */

import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Input } from 'antd';
import { CheckCircle, Copy, GraduationCap, Pencil, Plus, RefreshCw, Send, Trash2 } from 'lucide-react';

import {
  useLazyMessage,
  LazyPopconfirm,
  LazySelect,
  LazyEmpty,
  LazySpin,
} from '@/components/ui/lazyAntd';

import { SubmitSkillDialog } from '../../components/skill/SubmitSkillDialog';

import { SkillModal } from '../../components/skill/SkillModal';
import {
  useSkillStore,
  useSkillLoading,
  useSkillError,
  useActiveSkillsCount,
  useSkillTotal,
} from '../../stores/skill';

import type { SkillResponse } from '../../types/agent';

const { Search } = Input;

export const SkillList: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'disabled' | 'deprecated'>(
    'all'
  );
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<SkillResponse | null>(null);
  const [submittingSkill, setSubmittingSkill] = useState<SkillResponse | null>(null);

  // Store hooks
  const { skills } = useSkillStore();
  const isLoading = useSkillLoading();
  const error = useSkillError();
  const activeCount = useActiveSkillsCount();
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

      return true;
    });
  }, [skills, search, statusFilter]);

  const { listSkills, deleteSkill, updateSkillStatus, clearError } = useSkillStore();

  // Load data on mount
  useEffect(() => {
    listSkills();
  }, [listSkills]);

  // Clear error on unmount
  useEffect(() => {
    return () => {
      clearError();
    };
  }, [clearError]);

  // Show error message
  useEffect(() => {
    if (error) {
      message?.error(error);
    }
  }, [error, message]);

  // Handlers
  const handleCreate = useCallback(() => {
    setEditingSkill(null);
    setIsModalOpen(true);
  }, []);

  const handleEdit = useCallback((skill: SkillResponse) => {
    setEditingSkill(skill);
    setIsModalOpen(true);
  }, []);

  const handleStatusChange = useCallback(
    async (id: string, status: 'active' | 'disabled' | 'deprecated') => {
      try {
        await updateSkillStatus(id, status);
        message?.success(t('tenant.skills.statusUpdateSuccess'));
      } catch {
        // Error handled by store
      }
    },
    [updateSkillStatus, message, t]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteSkill(id);
        message?.success(t('tenant.skills.deleteSuccess'));
      } catch {
        // Error handled by store
      }
    },
    [deleteSkill, message, t]
  );

  const handleDuplicate = useCallback(
    async (skill: SkillResponse) => {
      const { createSkill } = useSkillStore.getState();
      try {
        // Build a SkillCreate payload from the source skill. We deliberately
        // ignore status so the copy starts fresh.
        await createSkill({
          name: `${skill.name} (copy)`,
          description: skill.description,
          tools: skill.tools ?? [],
          ...(skill.full_content ? { full_content: skill.full_content } : {}),
          metadata: { ...(skill.metadata ?? {}), duplicated_from: skill.id },
        });
        message?.success(t('common.success') ?? 'Duplicated');
      } catch {
        // Error handled by store
      }
    },
    [message, t]
  );

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
      active: {
        bg: 'bg-green-100 dark:bg-green-900/30',
        text: 'text-green-800 dark:text-green-300',
        dot: 'bg-green-500',
      },
      disabled: {
        bg: 'bg-slate-100 dark:bg-slate-700',
        text: 'text-slate-800 dark:text-slate-300',
        dot: 'bg-slate-400',
      },
      deprecated: {
        bg: 'bg-orange-100 dark:bg-orange-900/30',
        text: 'text-orange-800 dark:text-orange-300',
        dot: 'bg-orange-500',
      },
    };
    const { bg, text, dot } = config[status];
    return (
      <span
        className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${bg} ${text}`}
      >
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
          <p className="text-sm text-slate-500 mt-1">{t('tenant.skills.subtitle')}</p>
        </div>
        <button
          onClick={handleCreate}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
        >
          <Plus size={16} />
          {t('tenant.skills.createNew')}
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {t('tenant.skills.stats.total')}
              </p>
              <p className="text-2xl font-bold text-slate-900 dark:text-white mt-1">{total}</p>
            </div>
            <GraduationCap size={16} className="text-4xl text-primary-500" />
          </div>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {t('tenant.skills.stats.active')}
              </p>
              <p className="text-2xl font-bold text-green-600 dark:text-green-400 mt-1">
                {activeCount}
              </p>
            </div>
            <CheckCircle size={16} className="text-4xl text-green-500" />
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
              onChange={(e) => {
                setSearch(e.target.value);
              }}
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
          <button
            onClick={handleRefresh}
            className="inline-flex items-center justify-center px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700"
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <LazySpin size="large" />
        </div>
      ) : skills.length === 0 ? (
        <LazyEmpty description={t('tenant.skills.empty')} className="py-12" />
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

              {/* Tools */}
              <div className="mb-4">
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t('tenant.skills.tools')}: {skill.tools.length}
                </p>
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
                    onClick={() => {
                      handleEdit(skill);
                    }}
                    className="p-2 text-slate-600 dark:text-slate-400 hover:text-primary-600 dark:hover:text-primary-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700"
                    title="Edit"
                  >
                    <Pencil size={16} />
                  </button>
                  <button
                    onClick={() => {
                      void handleDuplicate(skill);
                    }}
                    className="p-2 text-slate-600 dark:text-slate-400 hover:text-primary-600 dark:hover:text-primary-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700"
                    title="Duplicate"
                    aria-label="Duplicate skill"
                  >
                    <Copy size={16} />
                  </button>
                  <button
                    onClick={() => {
                      setSubmittingSkill(skill);
                    }}
                    className="p-2 text-slate-600 dark:text-slate-400 hover:text-primary-600 dark:hover:text-primary-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700"
                    title="提交到精选库"
                    aria-label="Submit skill to curated library"
                  >
                    <Send size={16} />
                  </button>
                  <LazyPopconfirm
                    title={t('tenant.skills.deleteConfirm')}
                    onConfirm={() => handleDelete(skill.id)}
                    okText={t('common.confirm')}
                    cancelText={t('common.cancel')}
                  >
                    <button className="p-2 text-slate-600 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700">
                      <Trash2 size={16} />
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
      {/* Submit to curated library */}
      <SubmitSkillDialog
        skill={submittingSkill}
        open={submittingSkill !== null}
        onClose={() => {
          setSubmittingSkill(null);
        }}
      />
    </div>
  );
};

export default SkillList;
