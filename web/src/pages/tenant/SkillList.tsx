/**
 * Skill List Page
 *
 * Management page for Skills with CRUD operations and filtering/search functionality.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Input } from 'antd';
import {
  Copy,
  FileText,
  Pencil,
  Plus,
  RefreshCw,
  Search as SearchIcon,
  Send,
  Trash2,
} from 'lucide-react';

import {
  useLazyMessage,
  LazyPopconfirm,
  LazySelect,
  LazyEmpty,
  LazySpin,
} from '@/components/ui/lazyAntd';

import { SkillModal } from '../../components/skill/SkillModal';
import { SubmitSkillDialog } from '../../components/skill/SubmitSkillDialog';
import {
  useSkillStore,
  useSkillLoading,
  useSkillError,
  useActiveSkillsCount,
  useSkillTotal,
} from '../../stores/skill';

import type { SkillResponse } from '../../types/agent';

const { Search } = Input;

type SkillStatus = 'active' | 'disabled' | 'deprecated';

const pageText = 'text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.94_0.006_255)]';
const mutedText = 'text-[oklch(0.48_0.01_255)] dark:text-[oklch(0.68_0.008_255)]';
const surface =
  'border border-[oklch(0.9_0.006_255)] bg-[oklch(0.99_0.004_255)] dark:border-[oklch(0.28_0.006_255)] dark:bg-[oklch(0.18_0.006_255)]';
const iconButton =
  'inline-flex h-8 w-8 items-center justify-center rounded-[4px] text-[oklch(0.48_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] hover:text-[oklch(0.26_0.012_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] dark:text-[oklch(0.7_0.008_255)] dark:hover:bg-[oklch(0.24_0.006_255)] dark:hover:text-[oklch(0.94_0.006_255)]';

function StatusBadge({ status, label }: { status: SkillStatus; label: string }) {
  const config: Record<SkillStatus, { shell: string; dot: string }> = {
    active: {
      shell:
        'border-[oklch(0.78_0.08_155)] bg-[oklch(0.96_0.035_155)] text-[oklch(0.38_0.11_155)] dark:border-[oklch(0.44_0.08_155)] dark:bg-[oklch(0.24_0.04_155)] dark:text-[oklch(0.76_0.09_155)]',
      dot: 'bg-[oklch(0.58_0.14_155)]',
    },
    disabled: {
      shell:
        'border-[oklch(0.86_0.006_255)] bg-[oklch(0.96_0.004_255)] text-[oklch(0.46_0.008_255)] dark:border-[oklch(0.34_0.006_255)] dark:bg-[oklch(0.23_0.005_255)] dark:text-[oklch(0.72_0.006_255)]',
      dot: 'bg-[oklch(0.62_0.006_255)]',
    },
    deprecated: {
      shell:
        'border-[oklch(0.82_0.08_68)] bg-[oklch(0.97_0.035_68)] text-[oklch(0.48_0.1_68)] dark:border-[oklch(0.44_0.07_68)] dark:bg-[oklch(0.25_0.04_68)] dark:text-[oklch(0.8_0.09_68)]',
      dot: 'bg-[oklch(0.68_0.15_68)]',
    },
  };
  const { shell, dot } = config[status];

  return (
    <span
      className={`inline-flex h-6 items-center gap-1.5 rounded-full border px-2 text-[11px] font-medium ${shell}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {label}
    </span>
  );
}

function SummaryStat({ label, value }: { label: string; value: number }) {
  return (
    <div className={`rounded-[6px] px-4 py-3 ${surface}`}>
      <div className={`text-[11px] font-medium uppercase tracking-normal ${mutedText}`}>
        {label}
      </div>
      <div className={`mt-1 text-xl font-semibold leading-none ${pageText}`}>{value}</div>
    </div>
  );
}

export const SkillList: FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | SkillStatus>('all');
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
  const filteredSkills = useMemo(() => {
    return skills.filter((skill) => {
      if (search) {
        const searchLower = search.toLowerCase();
        const matchesName = skill.name.toLowerCase().includes(searchLower);
        const matchesDescription = skill.description.toLowerCase().includes(searchLower);
        if (!matchesName && !matchesDescription) {
          return false;
        }
      }

      if (statusFilter !== 'all' && skill.status !== statusFilter) {
        return false;
      }

      return true;
    });
  }, [skills, search, statusFilter]);

  const visibleCount = filteredSkills.length;
  const { listSkills, deleteSkill, updateSkillStatus, clearError } = useSkillStore();

  // Load data on mount
  useEffect(() => {
    void listSkills();
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
    async (id: string, status: SkillStatus) => {
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
          tools: skill.tools,
          ...(skill.full_content ? { full_content: skill.full_content } : {}),
          metadata: { ...skill.metadata, duplicated_from: skill.id },
        });
        message?.success(t('common.success'));
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
    void listSkills();
  }, [listSkills]);

  const handleRefresh = useCallback(() => {
    void listSkills();
  }, [listSkills]);

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className={`text-xs font-medium uppercase tracking-normal ${mutedText}`}>
            Skill Registry
          </div>
          <h1 className={`mt-2 text-2xl font-semibold leading-8 tracking-normal ${pageText}`}>
            {t('tenant.skills.title')}
          </h1>
          <p className={`mt-1 max-w-2xl text-sm ${mutedText}`}>{t('tenant.skills.subtitle')}</p>
        </div>
        <button
          type="button"
          onClick={handleCreate}
          className="inline-flex h-9 items-center justify-center gap-2 rounded-[4px] bg-[oklch(0.24_0.01_255)] px-4 text-sm font-medium text-[oklch(0.98_0.004_255)] transition-colors hover:bg-[oklch(0.31_0.012_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] dark:bg-[oklch(0.9_0.006_255)] dark:text-[oklch(0.17_0.006_255)] dark:hover:bg-[oklch(0.98_0.004_255)]"
        >
          <Plus size={16} />
          {t('tenant.skills.createNew')}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <SummaryStat label={t('tenant.skills.stats.total')} value={total} />
        <SummaryStat label={t('tenant.skills.stats.active')} value={activeCount} />
        <SummaryStat label={t('tenant.skills.stats.visible')} value={visibleCount} />
      </div>

      <div className={`rounded-[6px] p-3 ${surface}`}>
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <SearchIcon size={16} className={mutedText} />
            <Search
              placeholder={t('tenant.skills.searchPlaceholder')}
              value={search}
              enterButton={
                <>
                  <span className="sr-only">{t('common.search', 'Search')}</span>
                  <SearchIcon size={16} aria-hidden="true" />
                </>
              }
              onChange={(e) => {
                setSearch(e.target.value);
              }}
              allowClear
              className="min-w-0 flex-1"
            />
          </div>
          <LazySelect
            value={statusFilter}
            onChange={setStatusFilter}
            className="w-full md:w-44"
            options={[
              { label: t('common.status.all'), value: 'all' },
              { label: t('common.status.active'), value: 'active' },
              { label: t('common.status.disabled'), value: 'disabled' },
              { label: t('common.status.deprecated'), value: 'deprecated' },
            ]}
          />
          <button
            type="button"
            onClick={handleRefresh}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-[4px] border border-[oklch(0.86_0.006_255)] px-3 text-sm font-medium text-[oklch(0.34_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] dark:border-[oklch(0.34_0.006_255)] dark:text-[oklch(0.82_0.006_255)] dark:hover:bg-[oklch(0.24_0.006_255)]"
          >
            <RefreshCw size={16} />
            <span>{t('common.refresh')}</span>
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className={`flex justify-center rounded-[6px] py-12 ${surface}`}>
          <LazySpin size="large" />
        </div>
      ) : skills.length === 0 ? (
        <div className={`rounded-[6px] py-12 ${surface}`}>
          <LazyEmpty description={t('tenant.skills.empty')} />
        </div>
      ) : (
        <div className={`overflow-hidden rounded-[6px] ${surface}`}>
          {filteredSkills.map((skill) => (
            <div
              key={skill.id}
              className="grid gap-4 border-b border-[oklch(0.9_0.006_255)] px-4 py-4 last:border-b-0 hover:bg-[oklch(0.97_0.004_255)] dark:border-[oklch(0.28_0.006_255)] dark:hover:bg-[oklch(0.21_0.006_255)] lg:grid-cols-[minmax(0,1fr)_140px_260px] lg:items-center"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className={`truncate text-sm font-semibold ${pageText}`}>{skill.name}</h3>
                  <StatusBadge status={skill.status} label={t(`common.status.${skill.status}`)} />
                </div>
                <p className={`mt-2 line-clamp-2 text-sm ${mutedText}`}>{skill.description}</p>
              </div>

              <div className={`flex items-center gap-2 text-xs ${mutedText}`}>
                <FileText size={14} />
                <span>
                  {t('tenant.skills.tools')}: {skill.tools.length}
                </span>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between lg:justify-end">
                <LazySelect
                  value={skill.status}
                  onChange={(status: SkillStatus) => handleStatusChange(skill.id, status)}
                  className="w-full sm:w-36"
                  size="small"
                  options={[
                    { label: t('common.status.active'), value: 'active' },
                    { label: t('common.status.disabled'), value: 'disabled' },
                    { label: t('common.status.deprecated'), value: 'deprecated' },
                  ]}
                />
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      handleEdit(skill);
                    }}
                    className={iconButton}
                    title={t('tenant.skills.actions.edit')}
                    aria-label={t('tenant.skills.actions.editAria')}
                  >
                    <Pencil size={16} />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void handleDuplicate(skill);
                    }}
                    className={iconButton}
                    title={t('tenant.skills.actions.duplicate')}
                    aria-label={t('tenant.skills.actions.duplicateAria')}
                  >
                    <Copy size={16} />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setSubmittingSkill(skill);
                    }}
                    className={iconButton}
                    title={t('tenant.skills.actions.submitToCurated')}
                    aria-label={t('tenant.skills.actions.submitToCuratedAria')}
                  >
                    <Send size={16} />
                  </button>
                  <LazyPopconfirm
                    title={t('tenant.skills.deleteConfirm')}
                    onConfirm={() => handleDelete(skill.id)}
                    okText={t('common.confirm')}
                    cancelText={t('common.cancel')}
                  >
                    <button
                      type="button"
                      className={`${iconButton} hover:text-[oklch(0.55_0.18_25)]`}
                      title={t('tenant.skills.actions.delete')}
                      aria-label={t('tenant.skills.actions.deleteAria')}
                    >
                      <Trash2 size={16} />
                    </button>
                  </LazyPopconfirm>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {isModalOpen && (
        <SkillModal
          isOpen={isModalOpen}
          skill={editingSkill}
          onClose={handleModalClose}
          onSuccess={handleModalSuccess}
        />
      )}
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
