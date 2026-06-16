/**
 * Skill List Page
 *
 * Management page for Skills with CRUD operations and filtering/search functionality.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';

import { Input, Modal, Pagination, Switch } from 'antd';
import {
  Ban,
  Download,
  Eye,
  FileText,
  History,
  MessageSquare,
  Pencil,
  RefreshCw,
  RotateCcw,
  Search as SearchIcon,
  Trash2,
  Upload,
  UploadCloud,
  Wrench,
} from 'lucide-react';

import { useProjectStore } from '@/stores/project';
import {
  useSkillStore,
  useSkillLoading,
  useSkillError,
  useActiveSkillsCount,
  useSkillTotal,
} from '@/stores/skill';
import { useTenantStore } from '@/stores/tenant';

import { skillAPI } from '@/services/skillService';
import type { SkillListParams as SkillApiListParams } from '@/services/skillService';

import { SkillModal } from '@/components/skill/SkillModal';
import {
  useLazyMessage,
  LazyPopconfirm,
  LazySelect,
  LazyEmpty,
  LazySpin,
} from '@/components/ui/lazyAntd';

import { getSystemSkillConfigAction } from './skillListModel';

import type { SkillResponse, SkillVersionResponse } from '@/types/agent';

const { Search } = Input;
const { TextArea } = Input;

type SkillStatus = 'active' | 'disabled' | 'deprecated';
type SkillSource = NonNullable<SkillResponse['source']>;
type SkillLibraryView = 'all' | 'managed' | 'readonly';
type SkillScopeFilter = 'all' | 'system' | 'tenant' | 'project' | `project:${string}`;
type SkillImportScope = 'tenant' | 'project';
type SkillListQueryOverrides = {
  search?: string | undefined;
  status?: 'all' | SkillStatus | undefined;
  scope?: SkillScopeFilter | undefined;
  page?: number | undefined;
  pageSize?: number | undefined;
};
type SkillStoreListParams = SkillApiListParams & {
  page?: number | undefined;
  pageSize?: number | undefined;
};

const pageText = 'text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.94_0.006_255)]';
const mutedText = 'text-[oklch(0.48_0.01_255)] dark:text-[oklch(0.68_0.008_255)]';
const surface =
  'border border-[oklch(0.9_0.006_255)] bg-[oklch(0.99_0.004_255)] dark:border-[oklch(0.28_0.006_255)] dark:bg-[oklch(0.18_0.006_255)]';
const iconButton =
  'inline-flex h-8 w-8 items-center justify-center rounded-[4px] text-[oklch(0.48_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] hover:text-[oklch(0.26_0.012_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] dark:text-[oklch(0.7_0.008_255)] dark:hover:bg-[oklch(0.24_0.006_255)] dark:hover:text-[oklch(0.94_0.006_255)]';
const primaryButton =
  'inline-flex h-9 items-center justify-center gap-2 rounded-[4px] bg-[oklch(0.24_0.01_255)] px-4 text-sm font-medium text-[oklch(0.98_0.004_255)] transition-colors hover:bg-[oklch(0.31_0.012_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] dark:bg-[oklch(0.9_0.006_255)] dark:text-[oklch(0.17_0.006_255)] dark:hover:bg-[oklch(0.98_0.004_255)]';
const secondaryButton =
  'inline-flex h-9 items-center justify-center gap-2 rounded-[4px] border border-[oklch(0.86_0.006_255)] px-3 text-sm font-medium text-[oklch(0.34_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] dark:border-[oklch(0.34_0.006_255)] dark:text-[oklch(0.82_0.006_255)] dark:hover:bg-[oklch(0.24_0.006_255)]';

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

function getProjectFilterValue(projectId: string): `project:${string}` {
  return `project:${projectId}`;
}

function getProjectIdFromScopeFilter(scopeFilter: SkillScopeFilter): string | null {
  return scopeFilter.startsWith('project:') ? scopeFilter.slice('project:'.length) : null;
}

function getAgentWorkspacePath(pathname: string): string {
  const segments = pathname.split('/').filter(Boolean);
  const skillsIndex = segments.lastIndexOf('skills');

  if (skillsIndex === -1) {
    return '/tenant/agent-workspace';
  }

  return `/${segments.slice(0, skillsIndex).concat('agent-workspace').join('/')}`;
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
  const location = useLocation();
  const message = useLazyMessage();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | SkillStatus>('all');
  const [scopeFilter, setScopeFilter] = useState<SkillScopeFilter>('all');
  const [libraryView, setLibraryView] = useState<SkillLibraryView>('all');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isImportOpen, setIsImportOpen] = useState(false);
  const [importContent, setImportContent] = useState('');
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importOverwrite, setImportOverwrite] = useState(false);
  const [importScope, setImportScope] = useState<SkillImportScope>('tenant');
  const [importProjectId, setImportProjectId] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [editingSkill, setEditingSkill] = useState<SkillResponse | null>(null);
  const [versionSkill, setVersionSkill] = useState<SkillResponse | null>(null);
  const [versionRows, setVersionRows] = useState<SkillVersionResponse[]>([]);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);
  const [rollbackVersion, setRollbackVersion] = useState<number | null>(null);

  // Store hooks
  const { skills, tenantConfigs, page, pageSize } = useSkillStore();
  const isLoading = useSkillLoading();
  const error = useSkillError();
  const activeCount = useActiveSkillsCount();
  const total = useSkillTotal();
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const tenantId = currentTenant?.id ?? null;
  const projects = useProjectStore((state) => state.projects);
  const listProjects = useProjectStore((state) => state.listProjects);

  const projectNameById = useMemo(
    () => new Map(projects.map((project) => [project.id, project.name])),
    [projects]
  );

  const projectScopeOptions = useMemo(() => {
    const seen = new Set<string>();
    const options = projects.map((project) => {
      seen.add(project.id);
      return { id: project.id, name: project.name };
    });

    for (const skill of skills) {
      if (skill.scope === 'project' && skill.project_id && !seen.has(skill.project_id)) {
        seen.add(skill.project_id);
        options.push({ id: skill.project_id, name: skill.project_id });
      }
    }

    return options;
  }, [projects, skills]);

  const getSkillScopeLabel = useCallback(
    (skill: SkillResponse): string => {
      if (skill.scope === 'project') {
        return skill.project_id
          ? (projectNameById.get(skill.project_id) ?? skill.project_id)
          : t('tenant.skills.scope.project');
      }

      return t(`tenant.skills.scope.${skill.scope}`);
    },
    [projectNameById, t]
  );

  const buildListParams = useCallback(
    (overrides?: SkillListQueryOverrides): SkillStoreListParams => {
      const effectiveSearch = overrides?.search ?? search;
      const effectiveStatus = overrides?.status ?? statusFilter;
      const effectiveScope = overrides?.scope ?? scopeFilter;
      const projectId = getProjectIdFromScopeFilter(effectiveScope);
      const scope =
        projectId || effectiveScope === 'project'
          ? 'project'
          : effectiveScope === 'tenant' || effectiveScope === 'system'
            ? effectiveScope
            : undefined;
      return {
        search: effectiveSearch.trim() || undefined,
        status: effectiveStatus === 'all' ? undefined : effectiveStatus,
        scope,
        project_id: projectId ?? undefined,
        tenant_id: tenantId,
        page: overrides?.page ?? page,
        pageSize: overrides?.pageSize ?? pageSize,
      };
    },
    [page, pageSize, scopeFilter, search, statusFilter, tenantId]
  );

  // The API owns search/status/scope/project filtering and pagination.
  // Keep only UI-only library view filtering local.
  const filteredSkills = useMemo(() => {
    return skills.filter((skill) => {
      if (libraryView === 'managed' && !isManagedSkill(skill)) {
        return false;
      }

      if (libraryView === 'readonly' && isManagedSkill(skill)) {
        return false;
      }

      return true;
    });
  }, [libraryView, skills]);

  const visibleCount = filteredSkills.length;
  const managedCount = useMemo(() => skills.filter(isManagedSkill).length, [skills]);
  const readonlyCount = total - managedCount;
  const configBySystemSkillName = useMemo(
    () => new Map(tenantConfigs.map((config) => [config.system_skill_name, config.action])),
    [tenantConfigs]
  );
  const {
    listSkills,
    deleteSkill,
    clearError,
    listTenantConfigs,
    disableSystemSkill,
    enableSystemSkill,
  } = useSkillStore();

  // Load data on mount
  useEffect(() => {
    if (!tenantId) {
      return;
    }

    void listSkills({ page: 1, pageSize: 20, tenant_id: tenantId });
    void listTenantConfigs({ tenant_id: tenantId });
  }, [listSkills, listTenantConfigs, tenantId]);

  useEffect(() => {
    if (!currentTenant?.id) {
      return;
    }

    void listProjects(currentTenant.id, { page_size: 100 }).catch(() => {
      message?.error(t('tenant.skills.projectsLoadFailed'));
    });
  }, [currentTenant?.id, listProjects, message, t]);

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
    void navigate(getAgentWorkspacePath(location.pathname), {
      state: {
        suggestedPrompt: t('tenant.skills.createWithChatPrompt'),
      },
    });
  }, [location.pathname, navigate, t]);

  const resetImportState = useCallback(() => {
    setImportContent('');
    setImportFile(null);
    setImportOverwrite(false);
    setImportScope('tenant');
    setImportProjectId(null);
  }, []);

  const handleOpenImport = useCallback(() => {
    const filteredProjectId = getProjectIdFromScopeFilter(scopeFilter);
    if (filteredProjectId) {
      setImportScope('project');
      setImportProjectId(filteredProjectId);
    } else {
      setImportScope('tenant');
      setImportProjectId(null);
    }
    setIsImportOpen(true);
  }, [scopeFilter]);

  const handleImport = useCallback(async () => {
    if (!tenantId) {
      return;
    }
    if (!importFile && !importContent.trim()) {
      message?.error(t('tenant.skills.import.empty'));
      return;
    }
    if (importScope === 'project' && !importProjectId) {
      message?.error(t('tenant.skills.import.projectRequired'));
      return;
    }
    setIsImporting(true);
    try {
      const projectId = importScope === 'project' ? importProjectId : null;
      if (importFile) {
        await skillAPI.importZip(
          importFile,
          {
            overwrite: importOverwrite,
            scope: importScope,
            project_id: projectId,
          },
          { tenant_id: tenantId }
        );
      } else {
        await skillAPI.importPackage(
          {
            skill_md_content: importContent,
            overwrite: importOverwrite,
            scope: importScope,
            project_id: projectId,
          },
          { tenant_id: tenantId }
        );
      }
      message?.success(t('tenant.skills.import.success'));
      resetImportState();
      setIsImportOpen(false);
      void listSkills(buildListParams({ page: 1 }));
    } catch {
      message?.error(t('tenant.skills.import.failed'));
    } finally {
      setIsImporting(false);
    }
  }, [
    importContent,
    importFile,
    importOverwrite,
    importProjectId,
    importScope,
    listSkills,
    buildListParams,
    message,
    resetImportState,
    tenantId,
    t,
  ]);

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

  const handleDelete = useCallback(
    async (id: string) => {
      if (!tenantId) {
        return;
      }

      try {
        await deleteSkill(id, { tenant_id: tenantId });
        message?.success(t('tenant.skills.deleteSuccess'));
      } catch {
        // Error handled by store
      }
    },
    [deleteSkill, message, tenantId, t]
  );

  const handleDisableSystemSkill = useCallback(
    async (skillName: string) => {
      if (!tenantId) {
        return;
      }

      try {
        await disableSystemSkill(skillName, { tenant_id: tenantId });
        message?.success(t('tenant.skills.systemConfig.disableSuccess'));
        void listSkills(buildListParams({ page: 1 }));
      } catch {
        message?.error(t('tenant.skills.systemConfig.disableFailed'));
      }
    },
    [buildListParams, disableSystemSkill, listSkills, message, tenantId, t]
  );

  const handleRestoreSystemSkill = useCallback(
    async (skillName: string) => {
      if (!tenantId) {
        return;
      }

      try {
        await enableSystemSkill(skillName, { tenant_id: tenantId });
        message?.success(t('tenant.skills.systemConfig.restoreSuccess'));
        void listSkills(buildListParams({ page: 1 }));
      } catch {
        message?.error(t('tenant.skills.systemConfig.restoreFailed'));
      }
    },
    [buildListParams, enableSystemSkill, listSkills, message, tenantId, t]
  );

  const handleExport = useCallback(
    async (skill: SkillResponse) => {
      if (!tenantId) {
        return;
      }

      try {
        const exported = await skillAPI.exportPackage(skill.id, { tenant_id: tenantId });
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
    [message, tenantId, t]
  );

  const loadVersions = useCallback(
    async (skill: SkillResponse) => {
      if (!tenantId) {
        return;
      }

      setIsLoadingVersions(true);
      try {
        const result = await skillAPI.listVersions(skill.id, { tenant_id: tenantId });
        setVersionRows(result.versions);
      } catch {
        setVersionRows([]);
        message?.error(t('tenant.skills.versions.loadFailed'));
      } finally {
        setIsLoadingVersions(false);
      }
    },
    [message, tenantId, t]
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
      if (!tenantId) {
        return;
      }
      setRollbackVersion(versionNumber);
      try {
        const updated = await skillAPI.rollback(versionSkill.id, versionNumber, {
          tenant_id: tenantId,
        });
        setVersionSkill(updated);
        message?.success(t('tenant.skills.versions.rollbackSuccess'));
        await loadVersions(updated);
        void listSkills(buildListParams({ page }));
      } catch {
        message?.error(t('tenant.skills.versions.rollbackFailed'));
      } finally {
        setRollbackVersion(null);
      }
    },
    [buildListParams, listSkills, loadVersions, message, page, tenantId, t, versionSkill]
  );

  const handleModalClose = useCallback(() => {
    setIsModalOpen(false);
    setEditingSkill(null);
  }, []);

  const handleModalSuccess = useCallback(() => {
    setIsModalOpen(false);
    setEditingSkill(null);
    void listSkills(buildListParams({ page: 1 }));
  }, [buildListParams, listSkills]);

  const handleRefresh = useCallback(() => {
    void listSkills(buildListParams({ page }));
  }, [buildListParams, listSkills, page]);

  const handleSearchChange = useCallback(
    (value: string) => {
      setSearch(value);
      if (!value.trim()) {
        void listSkills(buildListParams({ search: '', page: 1 }));
      }
    },
    [buildListParams, listSkills]
  );

  const handleSearchSubmit = useCallback(
    (value: string) => {
      setSearch(value);
      void listSkills(buildListParams({ search: value, page: 1 }));
    },
    [buildListParams, listSkills]
  );

  const handleStatusFilterChange = useCallback(
    (value: 'all' | SkillStatus) => {
      setStatusFilter(value);
      void listSkills(buildListParams({ status: value, page: 1 }));
    },
    [buildListParams, listSkills]
  );

  const handleScopeFilterChange = useCallback(
    (value: SkillScopeFilter) => {
      setScopeFilter(value);
      void listSkills(buildListParams({ scope: value, page: 1 }));
    },
    [buildListParams, listSkills]
  );

  const handlePageChange = useCallback(
    (nextPage: number, nextPageSize: number) => {
      void listSkills(buildListParams({ page: nextPage, pageSize: nextPageSize }));
    },
    [buildListParams, listSkills]
  );

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
      <div className={`rounded-[8px] p-5 ${surface}`}>
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className={`text-xs font-medium uppercase tracking-normal ${mutedText}`}>
              {t('tenant.skills.registry')}
            </div>
            <h1 className={`mt-2 text-2xl font-semibold leading-8 tracking-normal ${pageText}`}>
              {t('tenant.skills.title')}
            </h1>
            <p className={`mt-1 max-w-2xl text-sm ${mutedText}`}>{t('tenant.skills.subtitle')}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={handleCreate} className={primaryButton}>
              <MessageSquare size={16} />
              {t('tenant.skills.createWithChat')}
            </button>
            <button type="button" onClick={handleOpenImport} className={secondaryButton}>
              <Upload size={16} />
              {t('tenant.skills.import.button')}
            </button>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <SummaryStat label={t('tenant.skills.stats.total')} value={total} />
          <SummaryStat label={t('tenant.skills.stats.active')} value={activeCount} />
          <SummaryStat label={t('tenant.skills.stats.visible')} value={visibleCount} />
        </div>
      </div>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div
          className="inline-flex w-fit rounded-[4px] border border-[oklch(0.86_0.006_255)] bg-[oklch(0.97_0.004_255)] p-0.5 dark:border-[oklch(0.34_0.006_255)] dark:bg-[oklch(0.2_0.006_255)]"
          role="group"
          aria-label={t('tenant.skills.libraryViewLabel')}
        >
          {(
            [
              { key: 'all' as const, count: total },
              { key: 'managed' as const, count: managedCount },
              { key: 'readonly' as const, count: readonlyCount },
            ] satisfies Array<{ key: SkillLibraryView; count: number }>
          ).map(({ key, count }) => {
            const active = libraryView === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => {
                  setLibraryView(key);
                }}
                className={`inline-flex h-8 items-center gap-2 rounded-[3px] px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] ${
                  active
                    ? 'bg-white text-[oklch(0.24_0.01_255)] shadow-sm dark:bg-[oklch(0.28_0.006_255)] dark:text-[oklch(0.94_0.006_255)]'
                    : 'text-[oklch(0.48_0.01_255)] hover:text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.68_0.008_255)] dark:hover:text-[oklch(0.94_0.006_255)]'
                }`}
                aria-pressed={active}
              >
                {t(`tenant.skills.libraryViews.${key}`)}
                <span className="text-[11px] opacity-70">{count}</span>
              </button>
            );
          })}
        </div>
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <div className="min-w-0 md:w-[360px]">
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
                handleSearchChange(e.target.value);
              }}
              onSearch={handleSearchSubmit}
              allowClear
              className="min-w-0 flex-1"
            />
          </div>
          <LazySelect
            aria-label={t('tenant.skills.statusFilterLabel')}
            value={statusFilter}
            onChange={handleStatusFilterChange}
            className="w-full md:w-44"
            options={[
              { label: t('common.status.all'), value: 'all' },
              { label: t('common.status.active'), value: 'active' },
              { label: t('common.status.disabled'), value: 'disabled' },
              { label: t('common.status.deprecated'), value: 'deprecated' },
            ]}
          />
          <select
            aria-label={t('tenant.skills.scopeFilterLabel')}
            value={scopeFilter}
            onChange={(event) => {
              handleScopeFilterChange(event.target.value as SkillScopeFilter);
            }}
            className="h-9 w-full rounded-[4px] border border-[oklch(0.86_0.006_255)] bg-white px-3 text-sm text-[oklch(0.34_0.01_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] dark:border-[oklch(0.34_0.006_255)] dark:bg-[oklch(0.18_0.006_255)] dark:text-[oklch(0.82_0.006_255)] md:w-48"
          >
            <option value="all">{t('tenant.skills.scope.all')}</option>
            <option value="system">{t('tenant.skills.scope.system')}</option>
            <option value="tenant">{t('tenant.skills.scope.tenant')}</option>
            <option value="project">{t('tenant.skills.scope.project')}</option>
            {projectScopeOptions.map((project) => (
              <option key={project.id} value={getProjectFilterValue(project.id)}>
                {project.name}
              </option>
            ))}
          </select>
          <button type="button" onClick={handleRefresh} className={secondaryButton}>
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
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {filteredSkills.length === 0 ? (
            <div className={`rounded-[6px] py-12 md:col-span-2 xl:col-span-3 ${surface}`}>
              <LazyEmpty description={t('tenant.skills.noResults')} />
            </div>
          ) : null}
          {filteredSkills.map((skill) => {
            const source = getSkillSource(skill);
            const managed = isManagedSkill(skill);
            const systemConfigAction = getSystemSkillConfigAction(skill, configBySystemSkillName);
            return (
              <article
                key={skill.id}
                className={`grid h-[196px] grid-rows-[56px_84px_56px] overflow-hidden rounded-[8px] transition-colors hover:bg-[oklch(0.97_0.004_255)] dark:hover:bg-[oklch(0.21_0.006_255)] ${surface}`}
              >
                <div className="flex min-h-14 items-center justify-between gap-3 border-b border-[oklch(0.9_0.006_255)] px-4 dark:border-[oklch(0.28_0.006_255)]">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[4px] border border-[oklch(0.86_0.006_255)] bg-white text-[oklch(0.42_0.14_255)] dark:border-[oklch(0.34_0.006_255)] dark:bg-[oklch(0.2_0.006_255)] dark:text-[oklch(0.74_0.12_255)]">
                      <Wrench size={15} />
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        handleView(skill);
                      }}
                      className={`min-w-0 truncate text-left text-sm font-semibold hover:underline ${pageText}`}
                    >
                      {skill.name}
                    </button>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <StatusBadge status={skill.status} label={t(`common.status.${skill.status}`)} />
                    {systemConfigAction ? (
                      <span
                        className={`inline-flex h-6 items-center gap-1.5 rounded-full border border-[oklch(0.84_0.08_75)] bg-[oklch(0.98_0.022_75)] px-2 text-[11px] font-medium text-[oklch(0.45_0.1_75)] dark:border-[oklch(0.38_0.07_75)] dark:bg-[oklch(0.21_0.035_75)] dark:text-[oklch(0.82_0.1_75)]`}
                      >
                        {t(`tenant.skills.systemConfig.${systemConfigAction}`)}
                      </span>
                    ) : null}
                    <SourceBadge source={source} label={t(`tenant.skills.source.${source}`)} />
                  </div>
                </div>

                <div className="overflow-hidden px-4 py-3">
                  <p className={`max-h-[40px] overflow-hidden text-sm leading-5 ${mutedText}`}>
                    {skill.description}
                  </p>
                </div>

                <div className="flex min-h-0 items-center justify-between gap-3 border-t border-[oklch(0.9_0.006_255)] px-4 py-2.5 dark:border-[oklch(0.28_0.006_255)]">
                  <div className="flex min-w-0 items-center gap-2 overflow-hidden">
                    <span
                      className={`inline-flex h-6 items-center gap-1 whitespace-nowrap text-xs ${mutedText}`}
                    >
                      <FileText size={14} />
                      {t('tenant.skills.card.tools')}: {skill.tools.length}
                    </span>
                    <span
                      className={`inline-flex h-6 max-w-[148px] shrink-0 items-center truncate rounded-full border border-[oklch(0.86_0.006_255)] px-2 text-[11px] font-medium ${mutedText}`}
                    >
                      {getSkillScopeLabel(skill)}
                    </span>
                    {skill.version_label || skill.current_version > 0 ? (
                      <span
                        className={`inline-flex h-6 shrink-0 items-center rounded-full border border-[oklch(0.86_0.006_255)] px-2 text-[11px] font-medium ${mutedText}`}
                      >
                        {t('tenant.skills.card.version', {
                          version: skill.version_label ?? String(skill.current_version),
                        })}
                      </span>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => {
                        handleView(skill);
                      }}
                      className={iconButton}
                      title={t('tenant.skills.actions.viewShort')}
                      aria-label={t('tenant.skills.actions.viewShort')}
                    >
                      <Eye size={14} />
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
                    {managed ? (
                      <>
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
                            handleOpenVersions(skill);
                          }}
                          className={iconButton}
                          title={t('tenant.skills.actions.versions')}
                          aria-label={t('tenant.skills.actions.versionsAria')}
                        >
                          <History size={16} />
                        </button>
                        <LazyPopconfirm
                          title={t('tenant.skills.deleteConfirm')}
                          onConfirm={() => {
                            void handleDelete(skill.id);
                          }}
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
                      </>
                    ) : null}
                    {skill.is_system_skill ? (
                      systemConfigAction ? (
                        <LazyPopconfirm
                          title={t('tenant.skills.systemConfig.restoreConfirm')}
                          onConfirm={() => {
                            void handleRestoreSystemSkill(skill.name);
                          }}
                          okText={t('common.confirm')}
                          cancelText={t('common.cancel')}
                        >
                          <button
                            type="button"
                            className={iconButton}
                            title={t('tenant.skills.systemConfig.restoreAction')}
                            aria-label={t('tenant.skills.systemConfig.restoreAria', {
                              name: skill.name,
                            })}
                          >
                            <RotateCcw size={16} />
                          </button>
                        </LazyPopconfirm>
                      ) : (
                        <LazyPopconfirm
                          title={t('tenant.skills.systemConfig.disableConfirm')}
                          onConfirm={() => {
                            void handleDisableSystemSkill(skill.name);
                          }}
                          okText={t('common.confirm')}
                          cancelText={t('common.cancel')}
                        >
                          <button
                            type="button"
                            className={iconButton}
                            title={t('tenant.skills.systemConfig.disableAction')}
                            aria-label={t('tenant.skills.systemConfig.disableAria', {
                              name: skill.name,
                            })}
                          >
                            <Ban size={16} />
                          </button>
                        </LazyPopconfirm>
                      )
                    ) : null}
                  </div>
                </div>
              </article>
            );
          })}
          {total > pageSize ? (
            <div className="md:col-span-2 xl:col-span-3">
              <Pagination
                aria-label={t('common.pagination.label', { defaultValue: 'Pagination' })}
                current={page}
                pageSize={pageSize}
                total={total}
                showSizeChanger
                pageSizeOptions={['20', '50', '100']}
                showTotal={(count, range) =>
                  t('common.pagination.total', {
                    start: range[0],
                    end: range[1],
                    total: count,
                    defaultValue: `${String(range[0])}-${String(range[1])} of ${String(count)}`,
                  })
                }
                onChange={handlePageChange}
                className="flex justify-end"
              />
            </div>
          ) : null}
        </div>
      )}

      {isModalOpen && editingSkill ? (
        <SkillModal
          isOpen={isModalOpen}
          skill={editingSkill}
          tenantId={tenantId}
          onClose={handleModalClose}
          onSuccess={handleModalSuccess}
        />
      ) : null}
      <Modal
        title={t('tenant.skills.import.title')}
        open={isImportOpen}
        onCancel={() => {
          resetImportState();
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
          <div className="grid gap-3 sm:grid-cols-2">
            <label className={`flex flex-col gap-1.5 text-sm ${mutedText}`}>
              <span>{t('tenant.skills.import.scopeLabel')}</span>
              <select
                aria-label={t('tenant.skills.import.scopeLabel')}
                value={importScope}
                onChange={(event) => {
                  const nextScope = event.target.value as SkillImportScope;
                  setImportScope(nextScope);
                  if (nextScope === 'project') {
                    setImportProjectId(importProjectId ?? projectScopeOptions[0]?.id ?? null);
                  } else {
                    setImportProjectId(null);
                  }
                }}
                className="h-9 rounded-[4px] border border-[oklch(0.86_0.006_255)] bg-white px-3 text-sm text-[oklch(0.34_0.01_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] dark:border-[oklch(0.34_0.006_255)] dark:bg-[oklch(0.18_0.006_255)] dark:text-[oklch(0.82_0.006_255)]"
              >
                <option value="tenant">{t('tenant.skills.import.scopeTenant')}</option>
                <option value="project" disabled={projectScopeOptions.length === 0}>
                  {t('tenant.skills.import.scopeProject')}
                </option>
              </select>
            </label>
            <label className={`flex flex-col gap-1.5 text-sm ${mutedText}`}>
              <span>{t('tenant.skills.import.projectLabel')}</span>
              <select
                aria-label={t('tenant.skills.import.projectLabel')}
                value={importProjectId ?? ''}
                disabled={importScope !== 'project'}
                onChange={(event) => {
                  setImportProjectId(event.target.value || null);
                }}
                className="h-9 rounded-[4px] border border-[oklch(0.86_0.006_255)] bg-white px-3 text-sm text-[oklch(0.34_0.01_255)] disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] dark:border-[oklch(0.34_0.006_255)] dark:bg-[oklch(0.18_0.006_255)] dark:text-[oklch(0.82_0.006_255)]"
              >
                <option value="">{t('tenant.skills.import.projectPlaceholder')}</option>
                {projectScopeOptions.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
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
    </div>
  );
};

export default SkillList;
