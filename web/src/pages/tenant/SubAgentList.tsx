/**
 * SubAgent List Page
 *
 * Management page for SubAgents with CRUD operations, template creation,
 * and filtering/search functionality.
 *
 * Performance optimizations:
 * - React.memo on StatusBadge, SubAgentCard, StatsCard
 * - useCallback for all event handlers
 * - useMemo for computed values (filtered subagents, menu items)
 */

import React, { useCallback, useEffect, useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  message,
  Popconfirm,
  Dropdown,
  Switch,
  Empty,
  Spin,
  Tooltip,
} from "antd";
import type { MenuProps } from "antd";
import {
  useSubAgentData,
  useSubAgentFiltersData,
  filterSubAgents,
  useSubAgentLoading,
  useSubAgentTemplates,
  useSubAgentTemplatesLoading,
  useSubAgentError,
  useEnabledSubAgentsCount,
  useAverageSuccessRate,
  useTotalInvocations,
  useListSubAgents,
  useListTemplates,
  useToggleSubAgent,
  useDeleteSubAgent,
  useCreateFromTemplate,
  useSetSubAgentFilters,
  useClearSubAgentError,
} from "../../stores/subagent";
import { SubAgentModal } from "../../components/subagent/SubAgentModal";
import type { SubAgentResponse, SubAgentTemplate } from "../../types/agent";

// Status Badge - Memoized component
const StatusBadge = React.memo(({ enabled }: { enabled: boolean }) => (
  <span
    className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${
      enabled
        ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
        : "bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-300"
    }`}
  >
    <span
      className={`h-1.5 w-1.5 rounded-full ${
        enabled ? "bg-green-500" : "bg-slate-400"
      }`}
    ></span>
    {enabled
      ? StatusBadgeTranslations.enabled
      : StatusBadgeTranslations.disabled}
  </span>
));
StatusBadge.displayName = "StatusBadge";

// Translation helper (inline to avoid hook in memo component)
const StatusBadgeTranslations = {
  enabled: "Enabled",
  disabled: "Disabled",
};

// Stats Card - Memoized component
interface StatsCardProps {
  title: string;
  value: string | number;
  icon: string;
  iconColor?: string;
  valueColor?: string;
}

const StatsCard = React.memo<StatsCardProps>(({
  title,
  value,
  icon,
  iconColor = "text-slate-400",
  valueColor = "text-slate-900 dark:text-white",
}) => (
  <div className="bg-surface-light dark:bg-surface-dark p-6 rounded-xl border border-slate-200 dark:border-slate-700">
    <div className="flex items-center justify-between">
      <p className="text-sm font-medium text-slate-500 dark:text-slate-400">
        {title}
      </p>
      <span className={`material-symbols-outlined ${iconColor}`}>
        {icon}
      </span>
    </div>
    <p className={`text-2xl font-bold ${valueColor} mt-2`}>
      {value}
    </p>
  </div>
));
StatsCard.displayName = "StatsCard";

// SubAgent Card - Memoized component
interface SubAgentCardProps {
  subagent: SubAgentResponse;
  onEdit: (subagent: SubAgentResponse) => void;
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
}

const SubAgentCard = React.memo<SubAgentCardProps>(({ subagent, onEdit, onToggle, onDelete }) => {
  const { t } = useTranslation();

  const handleToggle = useCallback((checked: boolean) => {
    onToggle(subagent.id, checked);
  }, [subagent.id, onToggle]);

  const handleEdit = useCallback(() => {
    onEdit(subagent);
  }, [subagent, onEdit]);

  const handleDelete = useCallback(() => {
    onDelete(subagent.id);
  }, [subagent.id, onDelete]);

  return (
    <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 hover:border-primary-300 dark:hover:border-primary-700 transition-colors overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-100 dark:border-slate-700">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center"
              style={{ backgroundColor: subagent.color + "20" }}
            >
              <span
                className="material-symbols-outlined"
                style={{ color: subagent.color }}
              >
                smart_toy
              </span>
            </div>
            <div>
              <h3 className="font-semibold text-slate-900 dark:text-white">
                {subagent.display_name}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {subagent.name}
              </p>
            </div>
          </div>
          <Switch
            checked={subagent.enabled}
            onChange={handleToggle}
            size="small"
          />
        </div>
      </div>

      {/* Body */}
      <div className="p-4 space-y-4">
        {/* Model */}
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-sm text-slate-400">
            memory
          </span>
          <span className="text-sm text-slate-600 dark:text-slate-300">
            {subagent.model === "inherit"
              ? t("tenant.subagents.inheritModel")
              : subagent.model}
          </span>
        </div>

        {/* Trigger Keywords */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="material-symbols-outlined text-sm text-slate-400">
              label
            </span>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {t("tenant.subagents.triggerKeywords")}
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {subagent.trigger.keywords.slice(0, 4).map((keyword, idx) => (
              <span
                key={idx}
                className="px-2 py-0.5 text-xs bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded"
              >
                {keyword}
              </span>
            ))}
            {subagent.trigger.keywords.length > 4 && (
              <Tooltip title={subagent.trigger.keywords.slice(4).join(", ")}>
                <span className="px-2 py-0.5 text-xs bg-slate-100 dark:bg-slate-700 text-slate-500 rounded cursor-help">
                  +{subagent.trigger.keywords.length - 4}
                </span>
              </Tooltip>
            )}
          </div>
        </div>

        {/* Tools Count */}
        <div className="flex items-center gap-4 text-sm">
          <div className="flex items-center gap-1 text-slate-500 dark:text-slate-400">
            <span className="material-symbols-outlined text-sm">build</span>
            <span>
              {subagent.allowed_tools.includes("*")
                ? t("tenant.subagents.allTools")
                : `${subagent.allowed_tools.length} ${t(
                    "tenant.subagents.tools"
                  )}`}
            </span>
          </div>
          {subagent.allowed_skills.length > 0 && (
            <div className="flex items-center gap-1 text-slate-500 dark:text-slate-400">
              <span className="material-symbols-outlined text-sm">
                auto_awesome
              </span>
              <span>
                {subagent.allowed_skills.length} {t("tenant.subagents.skills")}
              </span>
            </div>
          )}
        </div>

        {/* Stats */}
        <div className="pt-3 border-t border-slate-100 dark:border-slate-700 grid grid-cols-3 gap-2 text-center">
          <div>
            <p className="text-lg font-semibold text-slate-900 dark:text-white">
              {subagent.total_invocations}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t("tenant.subagents.invocations")}
            </p>
          </div>
          <div>
            <p className="text-lg font-semibold text-slate-900 dark:text-white">
              {Math.round(subagent.success_rate)}%
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t("tenant.subagents.successRate")}
            </p>
          </div>
          <div>
            <p className="text-lg font-semibold text-slate-900 dark:text-white">
              {subagent.avg_execution_time_ms > 0
                ? `${Math.round(subagent.avg_execution_time_ms / 1000)}s`
                : "-"}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t("tenant.subagents.avgTime")}
            </p>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="px-4 py-3 bg-slate-50 dark:bg-slate-900/50 border-t border-slate-100 dark:border-slate-700 flex items-center justify-between">
        <StatusBadge enabled={subagent.enabled} />
        <div className="flex items-center gap-2">
          <button
            onClick={handleEdit}
            className="p-1.5 text-slate-500 hover:text-primary-600 dark:text-slate-400 dark:hover:text-primary-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
            title={t("common.edit")}
          >
            <span className="material-symbols-outlined text-lg">edit</span>
          </button>
          <Popconfirm
            title={t("tenant.subagents.deleteConfirm")}
            onConfirm={handleDelete}
            okText={t("common.delete")}
            cancelText={t("common.cancel")}
            okButtonProps={{ danger: true }}
          >
            <button
              className="p-1.5 text-slate-500 hover:text-red-600 dark:text-slate-400 dark:hover:text-red-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
              title={t("common.delete")}
            >
              <span className="material-symbols-outlined text-lg">delete</span>
            </button>
          </Popconfirm>
        </div>
      </div>
    </div>
  );
});
SubAgentCard.displayName = "SubAgentCard";

export const SubAgentList: React.FC = () => {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<
    "all" | "enabled" | "disabled"
  >("all");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingSubAgent, setEditingSubAgent] =
    useState<SubAgentResponse | null>(null);

  // Store hooks - individual selectors for stable references
  const subagentsData = useSubAgentData();
  const filtersData = useSubAgentFiltersData();
  const templates = useSubAgentTemplates();
  const isLoading = useSubAgentLoading();
  const isTemplatesLoading = useSubAgentTemplatesLoading();
  const error = useSubAgentError();
  const enabledCount = useEnabledSubAgentsCount();
  const avgSuccessRate = useAverageSuccessRate();
  const totalInvocations = useTotalInvocations();

  // Action hooks - each returns a stable function reference
  const listSubAgents = useListSubAgents();
  const listTemplates = useListTemplates();
  const toggleSubAgent = useToggleSubAgent();
  const deleteSubAgent = useDeleteSubAgent();
  const createFromTemplate = useCreateFromTemplate();
  const setFilters = useSetSubAgentFilters();
  const clearError = useClearSubAgentError();

  // Compute filtered subagents with useMemo to avoid infinite loops
  const subagents = useMemo(
    () => filterSubAgents(subagentsData, filtersData),
    [subagentsData, filtersData]
  );

  // Load data on mount
  useEffect(() => {
    listSubAgents();
    listTemplates();
  }, [listSubAgents, listTemplates]);

  // Update filters when search or status changes
  useEffect(() => {
    setFilters({
      search,
      enabled: statusFilter === "all" ? null : statusFilter === "enabled",
    });
  }, [search, statusFilter, setFilters]);

  // Clear error on unmount
  useEffect(() => {
    return () => clearError();
  }, [clearError]);

  // Show error message
  useEffect(() => {
    if (error) {
      message.error(error);
    }
  }, [error]);

  // Handlers
  const handleCreate = useCallback(() => {
    setEditingSubAgent(null);
    setIsModalOpen(true);
  }, []);

  const handleEdit = useCallback((subagent: SubAgentResponse) => {
    setEditingSubAgent(subagent);
    setIsModalOpen(true);
  }, []);

  const handleToggle = useCallback(
    async (id: string, enabled: boolean) => {
      try {
        await toggleSubAgent(id, enabled);
        message.success(
          enabled
            ? t("tenant.subagents.enableSuccess")
            : t("tenant.subagents.disableSuccess")
        );
      } catch {
        // Error handled by store
      }
    },
    [toggleSubAgent, t]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteSubAgent(id);
        message.success(t("tenant.subagents.deleteSuccess"));
      } catch {
        // Error handled by store
      }
    },
    [deleteSubAgent, t]
  );

  const handleCreateFromTemplate = useCallback(
    async (templateName: string) => {
      try {
        const created = await createFromTemplate(templateName);
        message.success(t("tenant.subagents.createFromTemplateSuccess"));
        // Open modal to edit the newly created subagent
        setEditingSubAgent(created);
        setIsModalOpen(true);
      } catch {
        // Error handled by store
      }
    },
    [createFromTemplate, t]
  );

  const handleModalClose = useCallback(() => {
    setIsModalOpen(false);
    setEditingSubAgent(null);
  }, []);

  const handleModalSuccess = useCallback(() => {
    setIsModalOpen(false);
    setEditingSubAgent(null);
    listSubAgents();
  }, [listSubAgents]);

  const handleRefresh = useCallback(() => {
    listSubAgents();
  }, [listSubAgents]);

  // Template dropdown menu
  const templateMenuItems: MenuProps["items"] = useMemo(() => {
    if (templates.length === 0) {
      return [
        {
          key: "empty",
          label: t("tenant.subagents.noTemplates"),
          disabled: true,
        },
      ];
    }
    return templates.map((template: SubAgentTemplate) => ({
      key: template.name,
      label: (
        <div className="py-1">
          <div className="font-medium">{template.display_name}</div>
          <div className="text-xs text-slate-500">{template.description}</div>
        </div>
      ),
      onClick: () => handleCreateFromTemplate(template.name),
    }));
  }, [templates, t, handleCreateFromTemplate]);

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {t("tenant.subagents.title")}
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            {t("tenant.subagents.subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Dropdown
            menu={{ items: templateMenuItems }}
            trigger={["click"]}
            disabled={isTemplatesLoading}
          >
            <button className="inline-flex items-center justify-center gap-2 px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-lg text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors">
              <span className="material-symbols-outlined text-lg">
                content_copy
              </span>
              {t("tenant.subagents.fromTemplate")}
              <span className="material-symbols-outlined text-lg">
                expand_more
              </span>
            </button>
          </Dropdown>
          <button
            onClick={handleCreate}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
          >
            <span className="material-symbols-outlined text-lg">add</span>
            {t("tenant.subagents.createNew")}
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatsCard
          title={t("tenant.subagents.stats.total")}
          value={subagents.length}
          icon="smart_toy"
          iconColor="text-slate-400"
        />
        <StatsCard
          title={t("tenant.subagents.stats.enabled")}
          value={enabledCount}
          icon="check_circle"
          iconColor="text-green-500"
        />
        <StatsCard
          title={t("tenant.subagents.stats.successRate")}
          value={`${avgSuccessRate}%`}
          icon="trending_up"
          iconColor="text-blue-500"
        />
        <StatsCard
          title={t("tenant.subagents.stats.invocations")}
          value={totalInvocations.toLocaleString()}
          icon="bolt"
          iconColor="text-purple-500"
        />
      </div>

      {/* Filter Bar */}
      <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-700">
        <div className="p-4 flex flex-col sm:flex-row gap-4 justify-between items-center">
          {/* Search */}
          <div className="relative w-full sm:w-96">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <span className="material-symbols-outlined text-slate-400">
                search
              </span>
            </div>
            <input
              type="text"
              className="block w-full pl-10 pr-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              placeholder={t("tenant.subagents.searchPlaceholder")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          {/* Filters */}
          <div className="flex items-center gap-3">
            <select
              className="appearance-none bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg px-3 py-2 pr-8 text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-primary-500"
              value={statusFilter}
              onChange={(e) =>
                setStatusFilter(
                  e.target.value as "all" | "enabled" | "disabled"
                )
              }
            >
              <option value="all">{t("tenant.subagents.allStatus")}</option>
              <option value="enabled">
                {t("tenant.subagents.enabledOnly")}
              </option>
              <option value="disabled">
                {t("tenant.subagents.disabledOnly")}
              </option>
            </select>
            <button
              onClick={handleRefresh}
              className="p-2 text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              title={t("common.refresh")}
            >
              <span className="material-symbols-outlined">refresh</span>
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="p-4 border-t border-slate-200 dark:border-slate-700">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Spin size="large" />
            </div>
          ) : subagents.length === 0 ? (
            <Empty
              description={
                <span className="text-slate-500 dark:text-slate-400">
                  {search || statusFilter !== "all"
                    ? t("tenant.subagents.noResults")
                    : t("tenant.subagents.empty")}
                </span>
              }
            >
              {!search && statusFilter === "all" && (
                <button
                  onClick={handleCreate}
                  className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
                >
                  <span className="material-symbols-outlined text-lg">add</span>
                  {t("tenant.subagents.createFirst")}
                </button>
              )}
            </Empty>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
              {subagents.map((subagent) => (
                <SubAgentCard
                  key={subagent.id}
                  subagent={subagent}
                  onEdit={handleEdit}
                  onToggle={handleToggle}
                  onDelete={handleDelete}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Modal */}
      <SubAgentModal
        isOpen={isModalOpen}
        onClose={handleModalClose}
        onSuccess={handleModalSuccess}
        subagent={editingSubAgent}
      />
    </div>
  );
};

export default SubAgentList;
