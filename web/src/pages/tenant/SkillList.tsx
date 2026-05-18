/**
 * Skill List Page
 *
 * Management page for Skills with CRUD operations and filtering/search functionality.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Input, Modal, Switch } from 'antd';
import {
  ArrowUpCircle,
  Copy,
  Download,
  Eye,
  FileText,
  History,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Search as SearchIcon,
  Send,
  Trash2,
  Upload,
  UploadCloud,
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
import { skillAPI } from '../../services/skillService';
import {
  useSkillStore,
  useSkillLoading,
  useSkillError,
  useActiveSkillsCount,
  useSkillTotal,
} from '../../stores/skill';

import type { SkillResponse, SkillVersionResponse } from '../../types/agent';

const { Search } = Input;
const { TextArea } = Input;

type SkillStatus = 'active' | 'disabled' | 'deprecated';
type SkillSource = NonNullable<SkillResponse['source']>;

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

function getSkillSource(skill: SkillResponse): SkillSource {
  return skill.source ?? 'database';
}

function isManagedSkill(skill: SkillResponse): boolean {
  const source = getSkillSource(skill);
  return !skill.is_system_skill && (source === 'database' || source === 'hybrid');
}

function SourceBadge({ source, label }: { source: SkillSource; label: string }) {
  const dot =
    source === 'database'
      ? 'bg-[oklch(0.56_0.16_250)]'
      : source === 'filesystem'
        ? 'bg-[oklch(0.58_0.14_155)]'
        : 'bg-[oklch(0.62_0.006_255)]';

  return (
    <span
      className={`inline-flex h-6 items-center gap-1.5 rounded-full border border-[oklch(0.86_0.006_255)] px-2 text-[11px] font-medium ${mutedText}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {label}
    </span>
  );
}

export const SkillList: FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const message = useLazyMessage();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | SkillStatus>('all');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isImportOpen, setIsImportOpen] = useState(false);
  const [importContent, setImportContent] = useState('');
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importOverwrite, setImportOverwrite] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [editingSkill, setEditingSkill] = useState<SkillResponse | null>(null);
  const [submittingSkill, setSubmittingSkill] = useState<SkillResponse | null>(null);
  const [versionSkill, setVersionSkill] = useState<SkillResponse | null>(null);
  const [versionRows, setVersionRows] = useState<SkillVersionResponse[]>([]);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);
  const [rollbackVersion, setRollbackVersion] = useState<number | null>(null);

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
        const matchesVersion = [skill.version_label, skill.semver].some((value) =>
          value?.toLowerCase().includes(searchLower)
        );
        const matchesSource = [skill.source, skill.file_path].some((value) =>
          value?.toLowerCase().includes(searchLower)
        );
        const matchesMetadata = JSON.stringify(skill.metadata ?? {})
          .toLowerCase()
          .includes(searchLower);
        if (
          !matchesName &&
          !matchesDescription &&
          !matchesVersion &&
          !matchesSource &&
          !matchesMetadata
        ) {
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

  const handleImport = useCallback(async () => {
    if (!importFile && !importContent.trim()) {
      message?.error(t('tenant.skills.import.empty'));
      return;
    }
    setIsImporting(true);
    try {
      if (importFile) {
        await skillAPI.importZip(importFile, {
          overwrite: importOverwrite,
        });
      } else {
        await skillAPI.importPackage({
          skill_md_content: importContent,
          overwrite: importOverwrite,
        });
      }
      message?.success(t('tenant.skills.import.success'));
      setImportContent('');
      setImportFile(null);
      setImportOverwrite(false);
      setIsImportOpen(false);
      void listSkills();
    } catch {
      message?.error(t('tenant.skills.import.failed'));
    } finally {
      setIsImporting(false);
    }
  }, [importContent, importFile, importOverwrite, listSkills, message, t]);

  const handleEdit = useCallback((skill: SkillResponse) => {
    setEditingSkill(skill);
    setIsModalOpen(true);
  }, []);

  const handleView = useCallback(
    (skill: SkillResponse) => {
      const routeId = getSkillSource(skill) === 'filesystem' ? skill.name : skill.id;
      void navigate(encodeURIComponent(routeId));
    },
    [navigate]
  );

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

  const handleExport = useCallback(
    async (skill: SkillResponse) => {
      try {
        const exported = await skillAPI.exportPackage(skill.id);
        const blob = new Blob([JSON.stringify(exported, null, 2)], {
          type: 'application/json',
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${skill.name}.agentskill.json`;
        link.click();
        URL.revokeObjectURL(url);
        message?.success(t('tenant.skills.export.success'));
      } catch {
        message?.error(t('tenant.skills.export.failed'));
      }
    },
    [message, t]
  );

  const handleUpgrade = useCallback(
    async (skill: SkillResponse) => {
      try {
        const result = await skillAPI.upgrade(skill.id);
        if (result.action === 'noop') {
          message?.info(t('tenant.skills.upgrade.noop'));
        } else {
          message?.success(t('tenant.skills.upgrade.success'));
          void listSkills();
        }
      } catch {
        message?.error(t('tenant.skills.upgrade.failed'));
      }
    },
    [listSkills, message, t]
  );

  const loadVersions = useCallback(
    async (skill: SkillResponse) => {
      setIsLoadingVersions(true);
      try {
        const result = await skillAPI.listVersions(skill.id);
        setVersionRows(result.versions);
      } catch {
        setVersionRows([]);
        message?.error(t('tenant.skills.versions.loadFailed'));
      } finally {
        setIsLoadingVersions(false);
      }
    },
    [message, t]
  );

  const handleOpenVersions = useCallback(
    (skill: SkillResponse) => {
      setVersionSkill(skill);
      void loadVersions(skill);
    },
    [loadVersions]
  );

  const handleCloseVersions = useCallback(() => {
    setVersionSkill(null);
    setVersionRows([]);
    setRollbackVersion(null);
  }, []);

  const handleRollback = useCallback(
    async (versionNumber: number) => {
      if (!versionSkill) {
        return;
      }
      setRollbackVersion(versionNumber);
      try {
        const updated = await skillAPI.rollback(versionSkill.id, versionNumber);
        setVersionSkill(updated);
        message?.success(t('tenant.skills.versions.rollbackSuccess'));
        await loadVersions(updated);
        void listSkills({ search });
      } catch {
        message?.error(t('tenant.skills.versions.rollbackFailed'));
      } finally {
        setRollbackVersion(null);
      }
    },
    [listSkills, loadVersions, message, search, t, versionSkill]
  );

  const handleDuplicate = useCallback(
    async (skill: SkillResponse) => {
      const { createSkill } = useSkillStore.getState();
      try {
        // Build a SkillCreate payload from the source skill. We deliberately
        // ignore status so the copy starts fresh.
        await createSkill({
          name: `${skill.name}-copy`,
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
    void listSkills({ search });
  }, [listSkills, search]);

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className={`text-xs font-medium uppercase tracking-normal ${mutedText}`}>
            {t('tenant.skills.registry')}
          </div>
          <h1 className={`mt-2 text-2xl font-semibold leading-8 tracking-normal ${pageText}`}>
            {t('tenant.skills.title')}
          </h1>
          <p className={`mt-1 max-w-2xl text-sm ${mutedText}`}>{t('tenant.skills.subtitle')}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleCreate}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-[4px] bg-[oklch(0.24_0.01_255)] px-4 text-sm font-medium text-[oklch(0.98_0.004_255)] transition-colors hover:bg-[oklch(0.31_0.012_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] dark:bg-[oklch(0.9_0.006_255)] dark:text-[oklch(0.17_0.006_255)] dark:hover:bg-[oklch(0.98_0.004_255)]"
          >
            <Plus size={16} />
            {t('tenant.skills.createNew')}
          </button>
          <button
            type="button"
            onClick={() => {
              setIsImportOpen(true);
            }}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-[4px] border border-[oklch(0.86_0.006_255)] px-4 text-sm font-medium text-[oklch(0.34_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] dark:border-[oklch(0.34_0.006_255)] dark:text-[oklch(0.82_0.006_255)] dark:hover:bg-[oklch(0.24_0.006_255)]"
          >
            <Upload size={16} />
            {t('tenant.skills.import.button')}
          </button>
        </div>
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
              aria-label={t('tenant.skills.searchPlaceholder')}
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
              onSearch={(value) => {
                void listSkills({ search: value });
              }}
              allowClear
              className="min-w-0 flex-1"
            />
          </div>
          <LazySelect
            aria-label={t('tenant.skills.statusFilterLabel')}
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
          {filteredSkills.map((skill) => {
            const source = getSkillSource(skill);
            const managed = isManagedSkill(skill);
            return (
              <div
                key={skill.id}
                className="grid gap-4 border-b border-[oklch(0.9_0.006_255)] px-4 py-4 last:border-b-0 hover:bg-[oklch(0.97_0.004_255)] dark:border-[oklch(0.28_0.006_255)] dark:hover:bg-[oklch(0.21_0.006_255)] lg:grid-cols-[minmax(0,1fr)_140px_400px] lg:items-center"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        handleView(skill);
                      }}
                      className={`truncate text-left text-sm font-semibold hover:underline ${pageText}`}
                    >
                      {skill.name}
                    </button>
                    <StatusBadge status={skill.status} label={t(`common.status.${skill.status}`)} />
                    <SourceBadge source={source} label={t(`tenant.skills.source.${source}`)} />
                    {skill.version_label || skill.semver || skill.current_version > 0 ? (
                      <span
                        className={`inline-flex h-6 items-center rounded-full border border-[oklch(0.86_0.006_255)] px-2 text-[11px] font-medium ${mutedText}`}
                      >
                        {skill.semver ?? skill.version_label ?? `#${String(skill.current_version)}`}
                      </span>
                    ) : null}
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
                    aria-label={t('tenant.skills.statusSelectAria', { name: skill.name })}
                    value={skill.status}
                    onChange={(status: SkillStatus) => handleStatusChange(skill.id, status)}
                    className="w-full sm:w-36"
                    size="small"
                    disabled={!managed}
                    options={[
                      { label: t('common.status.active'), value: 'active' },
                      { label: t('common.status.disabled'), value: 'disabled' },
                      { label: t('common.status.deprecated'), value: 'deprecated' },
                    ]}
                  />
                  <div className="flex flex-wrap items-center gap-1.5 sm:justify-end">
                    <button
                      type="button"
                      onClick={() => {
                        handleView(skill);
                      }}
                      className={iconButton}
                      title={t('tenant.skills.actions.view')}
                      aria-label={t('tenant.skills.actions.viewAria')}
                    >
                      <Eye size={16} />
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        handleEdit(skill);
                      }}
                      className={iconButton}
                      title={t('tenant.skills.actions.edit')}
                      aria-label={t('tenant.skills.actions.editAria')}
                      disabled={!managed}
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
                        void handleExport(skill);
                      }}
                      className={iconButton}
                      title={t('tenant.skills.actions.export')}
                      aria-label={t('tenant.skills.actions.exportAria')}
                    >
                      <Download size={16} />
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        void handleUpgrade(skill);
                      }}
                      className={iconButton}
                      title={t('tenant.skills.actions.upgrade')}
                      aria-label={t('tenant.skills.actions.upgradeAria')}
                      disabled={!managed}
                    >
                      <ArrowUpCircle size={16} />
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        handleOpenVersions(skill);
                      }}
                      className={iconButton}
                      title={t('tenant.skills.actions.versions')}
                      aria-label={t('tenant.skills.actions.versionsAria')}
                      disabled={!managed}
                    >
                      <History size={16} />
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setSubmittingSkill(skill);
                      }}
                      className={iconButton}
                      title={t('tenant.skills.actions.submitToCurated')}
                      aria-label={t('tenant.skills.actions.submitToCuratedAria')}
                      disabled={!managed}
                    >
                      <Send size={16} />
                    </button>
                    <LazyPopconfirm
                      title={t('tenant.skills.deleteConfirm')}
                      onConfirm={() => {
                        if (managed) {
                          void handleDelete(skill.id);
                        }
                      }}
                      okText={t('common.confirm')}
                      cancelText={t('common.cancel')}
                      disabled={!managed}
                    >
                      <button
                        type="button"
                        className={`${iconButton} hover:text-[oklch(0.55_0.18_25)]`}
                        title={t('tenant.skills.actions.delete')}
                        aria-label={t('tenant.skills.actions.deleteAria')}
                        disabled={!managed}
                      >
                        <Trash2 size={16} />
                      </button>
                    </LazyPopconfirm>
                  </div>
                </div>
              </div>
            );
          })}
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
      <Modal
        title={t('tenant.skills.import.title')}
        open={isImportOpen}
        onCancel={() => {
          setImportFile(null);
          setIsImportOpen(false);
        }}
        onOk={() => {
          void handleImport();
        }}
        okText={t('tenant.skills.import.confirm')}
        confirmLoading={isImporting}
      >
        <div className="space-y-4">
          <label
            className={`flex cursor-pointer items-center justify-between gap-3 rounded-[6px] border border-dashed border-[oklch(0.82_0.006_255)] p-4 text-sm transition-colors hover:bg-[oklch(0.97_0.004_255)] dark:border-[oklch(0.34_0.006_255)] dark:hover:bg-[oklch(0.22_0.006_255)] ${mutedText}`}
          >
            <span className="flex min-w-0 items-center gap-3">
              <UploadCloud size={18} />
              <span className="min-w-0 truncate">
                {importFile ? importFile.name : t('tenant.skills.import.zipPlaceholder')}
              </span>
            </span>
            <span className="shrink-0 text-xs">{t('tenant.skills.import.zipButton')}</span>
            <input
              type="file"
              accept=".zip,application/zip"
              className="sr-only"
              onChange={(event) => {
                const nextFile = event.target.files?.[0] ?? null;
                setImportFile(nextFile);
                if (nextFile) {
                  setImportContent('');
                }
              }}
            />
          </label>
          <TextArea
            value={importContent}
            onChange={(event) => {
              setImportContent(event.target.value);
              if (event.target.value.trim()) {
                setImportFile(null);
              }
            }}
            placeholder={t('tenant.skills.import.placeholder')}
            disabled={importFile !== null}
            rows={12}
          />
          <label className={`flex items-center justify-between gap-3 text-sm ${mutedText}`}>
            <span>{t('tenant.skills.import.overwrite')}</span>
            <Switch checked={importOverwrite} onChange={setImportOverwrite} />
          </label>
        </div>
      </Modal>
      <Modal
        title={versionSkill ? t('tenant.skills.versions.title', { name: versionSkill.name }) : ''}
        open={versionSkill !== null}
        onCancel={handleCloseVersions}
        footer={null}
      >
        {isLoadingVersions ? (
          <div className="flex justify-center py-10">
            <LazySpin />
          </div>
        ) : versionRows.length === 0 ? (
          <div className="py-8">
            <LazyEmpty description={t('tenant.skills.versions.empty')} />
          </div>
        ) : (
          <div className="max-h-[420px] overflow-auto divide-y divide-[oklch(0.9_0.006_255)] dark:divide-[oklch(0.28_0.006_255)]">
            {versionRows.map((version) => {
              const isCurrent = versionSkill?.current_version === version.version_number;
              return (
                <div
                  key={version.id}
                  className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`text-sm font-semibold ${pageText}`}>
                        {version.version_label ?? `#${String(version.version_number)}`}
                      </span>
                      <span className={`text-xs ${mutedText}`}>#{version.version_number}</span>
                      {isCurrent ? (
                        <span className="rounded-full border border-[oklch(0.78_0.08_155)] bg-[oklch(0.96_0.035_155)] px-2 py-0.5 text-[11px] font-medium text-[oklch(0.38_0.11_155)] dark:border-[oklch(0.44_0.08_155)] dark:bg-[oklch(0.24_0.04_155)] dark:text-[oklch(0.76_0.09_155)]">
                          {t('tenant.skills.versions.current')}
                        </span>
                      ) : null}
                    </div>
                    {version.change_summary ? (
                      <div className={`mt-1 text-sm ${mutedText}`}>{version.change_summary}</div>
                    ) : null}
                    <div className={`mt-1 text-xs ${mutedText}`}>
                      {t('tenant.skills.versions.createdBy', {
                        author: version.created_by,
                        date: new Date(version.created_at).toLocaleString(),
                      })}
                    </div>
                  </div>
                  {!isCurrent ? (
                    <LazyPopconfirm
                      title={t('tenant.skills.versions.rollbackConfirm')}
                      onConfirm={() => {
                        void handleRollback(version.version_number);
                      }}
                      okText={t('common.confirm')}
                      cancelText={t('common.cancel')}
                    >
                      <button
                        type="button"
                        className="inline-flex h-8 items-center justify-center gap-2 rounded-[4px] border border-[oklch(0.86_0.006_255)] px-3 text-sm font-medium text-[oklch(0.34_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] disabled:cursor-not-allowed disabled:opacity-60 dark:border-[oklch(0.34_0.006_255)] dark:text-[oklch(0.82_0.006_255)] dark:hover:bg-[oklch(0.24_0.006_255)]"
                        disabled={rollbackVersion !== null}
                      >
                        <RotateCcw size={14} />
                        {rollbackVersion === version.version_number
                          ? t('tenant.skills.versions.rollingBack')
                          : t('tenant.skills.versions.rollback')}
                      </button>
                    </LazyPopconfirm>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </Modal>
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
