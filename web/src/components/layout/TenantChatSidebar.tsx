/**
 * TenantChatSidebar - Tenant-level conversation history sidebar
 *
 * Shows conversations across all projects in the tenant.
 * This replaces the traditional tenant navigation as the primary sidebar.
 *
 * Features:
 * - Draggable resize for width adjustment (optimized with RAF)
 * - Collapsible to icon-only mode (controlled by parent)
 * - Performance optimized to prevent re-renders during drag
 */

import * as React from 'react';
import { useState, useEffect, useCallback, useMemo, useRef, useLayoutEffect, memo } from 'react';

import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate, NavLink } from 'react-router-dom';

import {
  Plus,
  MessageSquare,
  Trash2,
  Edit3,
  Bot,
  FolderOpen,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useConversationsStore } from '@/stores/agent/conversationsStore';
import { useAgentV3Store } from '@/stores/agentV3';
import { useProjectStore } from '@/stores/project';
import {
  useCurrentWorkspace,
  useWorkspaceActions,
  useWorkspaceTasks,
  useWorkspaces,
} from '@/stores/workspace';

import { projectAPI } from '@/services/api';

import { buildAgentWorkspacePath } from '@/utils/agentWorkspacePath';
import { formatDistanceToNow } from '@/utils/date';
import {
  lastProjectIdStorageKey,
  lastProjectSelectionSourceStorageKey,
  MANUAL_PROJECT_SELECTION_SOURCE,
  persistLastProjectId,
} from '@/utils/projectSelectionPersistence';

import {
  getContextualTopNavItems,
  groupTenantTopNavItems,
  isContextualTopNavItemActive,
} from '@/components/layout/tenantNavigation';
import { LazyButton, LazyInput } from '@/components/ui/lazyAntd';

import { Resizer } from '../agent/Resizer';

import type { Conversation } from '@/types/agent';
import type { Project } from '@/types/memory';

interface ConversationWithProject extends Conversation {
  projectId: string;
  projectName: string;
  workspaceTaskTitle?: string | null | undefined;
  workspaceName?: string | null | undefined;
}

interface ConversationItemProps {
  activeItemRef?: React.Ref<HTMLDivElement> | undefined;
  conversation: ConversationWithProject;
  grouped?: boolean | undefined;
  isActive: boolean;
  onSelect: () => void;
  onDelete: (e: React.MouseEvent) => void;
  onRename?: ((e: React.MouseEvent) => void) | undefined;
}

type ConversationListSection =
  | { type: 'conversation'; conversation: ConversationWithProject }
  | {
      type: 'workspace';
      id: string;
      groupKey: string;
      workspaceTitle: string;
      conversations: ConversationWithProject[];
    };

// Constants for resize constraints
const SIDEBAR_MIN_WIDTH = 200;
const SIDEBAR_MAX_WIDTH = 400;
const SIDEBAR_DEFAULT_WIDTH = 256;
const SIDEBAR_COLLAPSED_WIDTH = 80;
const COLLAPSE_THRESHOLD = 120; // Width below which sidebar collapses
const PROJECT_SWITCHER_PAGE_SIZE = 25;
const PROJECT_SEARCH_PAGE_SIZE = 100;
const PROJECT_SEARCH_DEBOUNCE_MS = 250;
const CONVERSATION_AUTO_FILL_PAGE_LIMIT = 2;

function projectBelongsToTenant(
  project: Project | null | undefined,
  tenantId: string | undefined
): project is Project {
  return !!project && (!tenantId || project.tenant_id === tenantId);
}

function readStoredProjectSelectionValue(key: string | null): string | null {
  if (!key || typeof window === 'undefined') {
    return null;
  }

  try {
    const rawValue = window.localStorage.getItem(key);
    if (!rawValue) {
      return null;
    }
    try {
      const parsedValue: unknown = JSON.parse(rawValue);
      return typeof parsedValue === 'string' ? parsedValue : null;
    } catch {
      return rawValue;
    }
  } catch {
    return null;
  }
}

function readManualStoredProjectId(tenantId: string | undefined): string | null {
  const selectionSource = readStoredProjectSelectionValue(
    lastProjectSelectionSourceStorageKey(tenantId)
  );
  if (selectionSource !== MANUAL_PROJECT_SELECTION_SOURCE) {
    return null;
  }
  return readStoredProjectSelectionValue(lastProjectIdStorageKey(tenantId));
}

function conversationBelongsToProject(
  conversation: Conversation,
  projectId: string | null
): boolean {
  if (!projectId) {
    return false;
  }
  return !conversation.project_id || conversation.project_id === projectId;
}

function readMetadataString(
  metadata: Record<string, unknown> | undefined,
  key: string
): string | null {
  const value = metadata?.[key];
  return typeof value === 'string' && value.trim().length > 0 ? value : null;
}

function workspaceIdFromConversation(conversation: Conversation): string | null {
  if (conversation.workspace_id) {
    return conversation.workspace_id;
  }
  const metadataWorkspaceId = readMetadataString(conversation.metadata, 'workspace_id');
  if (metadataWorkspaceId) {
    return metadataWorkspaceId;
  }
  if (!conversation.id.startsWith('workspace-')) {
    return null;
  }
  const [, workspaceId] = conversation.id.split(':');
  return workspaceId && workspaceId.length > 0 ? workspaceId : null;
}

function workspaceNodeIdFromConversation(conversation: Conversation): string | null {
  if (conversation.linked_workspace_task_id) {
    return conversation.linked_workspace_task_id;
  }
  const metadataTaskId =
    readMetadataString(conversation.metadata, 'workspace_task_id') ??
    readMetadataString(conversation.metadata, 'linked_workspace_task_id');
  if (metadataTaskId) {
    return metadataTaskId;
  }
  if (!conversation.id.startsWith('workspace-')) {
    return null;
  }
  const [, , nodeId] = conversation.id.split(':');
  return nodeId && nodeId.length > 0 ? nodeId : null;
}

function isDerivedAgentConversation(conversation: Conversation): boolean {
  if (conversation.parent_conversation_id) {
    return true;
  }

  const looksLikeGeneratedAgentSessionTitle = /\bsession\s*$/i.test(conversation.title.trim());
  if (
    looksLikeGeneratedAgentSessionTitle &&
    !conversation.workspace_id &&
    !conversation.linked_workspace_task_id
  ) {
    return true;
  }

  return Boolean(
    readMetadataString(conversation.metadata, 'spawned_by_agent_id') ||
    readMetadataString(conversation.metadata, 'spawned_agent_id')
  );
}

function cleanWorkspaceTitle(title: string): string {
  return title
    .replace(/^Workspace Worker\s*-\s*/i, '')
    .replace(/^Workspace Verification Gate\s*-\s*/i, '')
    .replace(/^Workspace Supervisor Decision\s*-\s*/i, '')
    .replace(/^Workspace Chat\s*-\s*/i, '')
    .replace(/^Workspace\s+/i, '')
    .trim();
}

function isOpaqueTaskTitle(title: string): boolean {
  return (
    /^node-[a-z0-9._-]+$/i.test(title) ||
    /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(title) ||
    /^(worker|verifier|supervisor|architect|builder|chat|workspace)$/i.test(title)
  );
}

function workspaceTitleForConversation(
  conversation: ConversationWithProject,
  t: ReturnType<typeof useTranslation>['t']
): string {
  return (
    conversation.workspaceName ??
    t('agent.sidebar.unknownWorkspace', {
      defaultValue: 'Unknown workspace',
    })
  );
}

function workspaceTaskTitleForConversation(
  conversation: ConversationWithProject,
  rawTitle: string,
  t: ReturnType<typeof useTranslation>['t']
): string {
  const explicitTitle =
    conversation.workspaceTaskTitle ??
    readMetadataString(conversation.metadata, 'workspace_task_title') ??
    readMetadataString(conversation.metadata, 'linked_workspace_task_title') ??
    readMetadataString(conversation.metadata, 'task_title');
  const cleanedExplicitTitle = explicitTitle ? cleanWorkspaceTitle(explicitTitle) : null;
  if (cleanedExplicitTitle && !isOpaqueTaskTitle(cleanedExplicitTitle)) {
    return cleanedExplicitTitle;
  }

  const cleanedRawTitle = cleanWorkspaceTitle(rawTitle);
  if (cleanedRawTitle && !isOpaqueTaskTitle(cleanedRawTitle)) {
    return cleanedRawTitle;
  }

  return t('agent.sidebar.workspaceTaskTitleFallback', 'Workspace task');
}

function workspaceRoleLabel(
  conversation: Conversation,
  title: string,
  t: ReturnType<typeof useTranslation>['t']
): string | null {
  const id = conversation.id.toLowerCase();
  if (/^workspace worker\s*-/i.test(title) || id.startsWith('workspace-worker:')) {
    return t('agent.sidebar.workspaceRole.worker', 'Worker');
  }
  if (/^workspace verification gate\s*-/i.test(title) || id.startsWith('workspace-verifier:')) {
    return t('agent.sidebar.workspaceRole.verifier', 'Verifier');
  }
  if (
    /^workspace supervisor decision\s*-/i.test(title) ||
    id.startsWith('workspace-contract:supervisor-decision:')
  ) {
    return t('agent.sidebar.workspaceRole.supervisor', 'Supervisor');
  }
  if (id.startsWith('workspace-architect:') || /architect/i.test(title)) {
    return t('agent.sidebar.workspaceRole.architect', 'Architect');
  }
  if (id.startsWith('workspace-builder:') || /builder/i.test(title)) {
    return t('agent.sidebar.workspaceRole.builder', 'Builder');
  }
  if (/^workspace chat\s*-/i.test(title) || id.startsWith('workspace-chat:')) {
    return t('agent.sidebar.workspaceRole.chat', 'Chat');
  }
  if (conversation.workspace_id || id.startsWith('workspace-')) {
    return t('agent.sidebar.workspaceRole.workspace', 'Workspace');
  }
  return null;
}

function buildConversationDisplay(
  conversation: ConversationWithProject,
  t: ReturnType<typeof useTranslation>['t'],
  timeAgo: string
) {
  const fallbackTitle = t('agent.sidebar.untitled', 'Untitled Conversation');
  const rawTitle = conversation.title || fallbackTitle;
  const roleLabel = workspaceRoleLabel(conversation, rawTitle, t);
  const isWorkspaceConversation = Boolean(roleLabel || workspaceIdFromConversation(conversation));
  const taskTitle = isWorkspaceConversation
    ? workspaceTaskTitleForConversation(conversation, rawTitle, t)
    : rawTitle;
  const displayTitle = isWorkspaceConversation
    ? taskTitle || t('agent.sidebar.workspaceTaskTitleFallback', 'Workspace task')
    : rawTitle;
  const contextLabel = isWorkspaceConversation
    ? workspaceTitleForConversation(conversation, t)
    : conversation.projectName;

  return {
    contextLabel,
    displayTitle,
    isWorkspaceConversation,
    roleLabel,
    taskTitle,
    timeAgo,
  };
}

function buildConversationSections(
  conversations: ConversationWithProject[],
  t: ReturnType<typeof useTranslation>['t']
): ConversationListSection[] {
  const sections: ConversationListSection[] = [];

  for (const conversation of conversations) {
    const display = buildConversationDisplay(conversation, t, '');
    if (!display.isWorkspaceConversation) {
      sections.push({ type: 'conversation', conversation });
      continue;
    }

    const workspaceKey = workspaceIdFromConversation(conversation) ?? display.contextLabel;
    const sectionGroupKey = `workspace:${workspaceKey}`;
    const previousSection = sections[sections.length - 1];

    if (previousSection?.type === 'workspace' && previousSection.groupKey === sectionGroupKey) {
      previousSection.conversations.push(conversation);
      continue;
    }

    sections.push({
      type: 'workspace',
      id: `${sectionGroupKey}:${sections.length.toString()}`,
      groupKey: sectionGroupKey,
      workspaceTitle: display.contextLabel,
      conversations: [conversation],
    });
  }

  return sections;
}

function conversationActivityDate(conversation: Conversation): string {
  return conversation.updated_at || conversation.created_at;
}

// Memoized ConversationItem to prevent unnecessary re-renders (rerender-memo)
const ConversationItem: React.FC<ConversationItemProps> = memo(
  ({ activeItemRef, conversation, grouped = false, isActive, onSelect, onDelete, onRename }) => {
    const { t } = useTranslation();
    const timeAgo = React.useMemo(() => {
      try {
        return formatDistanceToNow(conversationActivityDate(conversation));
      } catch {
        return '';
      }
    }, [conversation]);

    const display = React.useMemo(
      () => buildConversationDisplay(conversation, t, timeAgo),
      [conversation, t, timeAgo]
    );
    const primaryTitle = display.displayTitle;
    const contextParts =
      grouped && display.isWorkspaceConversation
        ? [display.roleLabel].filter((part): part is string => Boolean(part))
        : [display.roleLabel, display.contextLabel].filter((part): part is string => Boolean(part));

    return (
      <div
        ref={activeItemRef}
        role="button"
        tabIndex={0}
        onClick={onSelect}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSelect();
          }
        }}
        className={`
        group relative p-3 rounded-xl mb-1 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset
        transition-[color,background-color,border-color,box-shadow,opacity,transform,width] duration-200 border
        ${
          isActive
            ? 'bg-slate-50 dark:bg-slate-800/60 border-slate-200 dark:border-slate-700 text-slate-900 dark:text-slate-100'
            : 'bg-transparent border-transparent text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/40'
        }
      `}
      >
        <div className="flex items-start gap-2">
          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium text-sm truncate" title={primaryTitle}>
                {primaryTitle}
              </p>
              <div className="flex shrink-0 items-center gap-1 text-xs text-slate-400">
                {conversation.status === 'active' ? (
                  <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden />
                ) : null}
                <span>{display.timeAgo}</span>
              </div>
            </div>
            {contextParts.length > 0 ? (
              <div className="mt-1 flex min-w-0 items-center gap-1.5 text-[11px] leading-4 text-slate-400">
                {contextParts.map((part, index) => (
                  <React.Fragment key={`${part}-${index.toString()}`}>
                    {index > 0 ? (
                      <span className="shrink-0 text-slate-300 dark:text-slate-600">·</span>
                    ) : null}
                    <span
                      className={
                        index === 0 && display.roleLabel === part
                          ? 'shrink-0 font-medium uppercase'
                          : 'truncate'
                      }
                    >
                      {part}
                    </span>
                  </React.Fragment>
                ))}
              </div>
            ) : null}
          </div>

          {/* Actions */}
          <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
            {onRename ? (
              <button
                type="button"
                aria-label={t('agent.sidebar.rename', 'Rename')}
                title={t('agent.sidebar.rename', 'Rename')}
                className="inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                onClick={(event) => {
                  event.stopPropagation();
                  onRename(event);
                }}
              >
                <Edit3 size={14} />
              </button>
            ) : null}
            <button
              type="button"
              aria-label={t('agent.sidebar.delete', 'Delete')}
              title={t('agent.sidebar.delete', 'Delete')}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-red-500/70 transition-colors hover:bg-red-50 hover:text-red-700 focus-visible:text-red-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/40 dark:text-red-300/70 dark:hover:bg-red-950/30 dark:hover:text-red-200 dark:focus-visible:text-red-200"
              onClick={(event) => {
                event.stopPropagation();
                onDelete(event);
              }}
            >
              <Trash2 size={14} />
            </button>
          </div>
        </div>
      </div>
    );
  }
);
ConversationItem.displayName = 'ConversationItem';

const ConversationGroupHeader: React.FC<{
  collapsed: boolean;
  conversationCount: number;
  onToggle: () => void;
  workspaceTitle: string;
}> = memo(({ collapsed, conversationCount, onToggle, workspaceTitle }) => (
  <div className="mb-1 mt-3 first:mt-1">
    <button
      type="button"
      aria-expanded={!collapsed}
      onClick={onToggle}
      className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left transition-colors duration-150 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:hover:bg-slate-800/40"
    >
      <span className="flex h-4 w-4 shrink-0 items-center justify-center text-slate-400">
        {collapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
      </span>
      <span className="min-w-0 flex-1">
        <span
          className="block truncate text-[12px] font-medium leading-5 text-slate-700 dark:text-slate-300"
          title={workspaceTitle}
        >
          {workspaceTitle}
        </span>
      </span>
      <span
        className="shrink-0 rounded-full bg-slate-100 px-1.5 text-[10px] leading-4 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
        aria-label={`${conversationCount.toString()} conversations`}
      >
        {conversationCount}
      </span>
    </button>
  </div>
));
ConversationGroupHeader.displayName = 'ConversationGroupHeader';

// Simple Tooltip component for collapsed state
const Tooltip: React.FC<{ children: React.ReactNode; title: string }> = ({ children, title }) => (
  <div className="group relative">
    {children}
    <div className="absolute left-full ml-2 px-2 py-1 bg-slate-800 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-50 pointer-events-none">
      {title}
    </div>
  </div>
);

export interface TenantChatSidebarProps {
  tenantId?: string | undefined;
  /** Controlled collapsed state */
  collapsed?: boolean | undefined;
  /** Callback when collapsed state changes */
  onCollapsedChange?: ((collapsed: boolean) => void) | undefined;
  /** When true, always visible (used inside mobile drawer) */
  mobile?: boolean | undefined;
}

export const TenantChatSidebar: React.FC<TenantChatSidebarProps> = ({
  tenantId,
  collapsed: controlledCollapsed,
  onCollapsedChange,
  mobile = false,
}) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();

  // Use ref for width during drag to avoid re-renders
  const widthRef = useRef(SIDEBAR_DEFAULT_WIDTH);
  const sidebarRef = useRef<HTMLElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const activeConversationItemRef = useRef<HTMLDivElement | null>(null);

  // Internal state for uncontrolled mode
  const [internalCollapsed, setInternalCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT_WIDTH);
  const [isDragging, setIsDragging] = useState(false);

  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [projectSearchResults, setProjectSearchResults] = useState<Project[]>([]);
  const [projectSearchTotal, setProjectSearchTotal] = useState(0);
  const [projectSearchPage, setProjectSearchPage] = useState(0);
  const [projectSearchQuery, setProjectSearchQuery] = useState('');
  const [isProjectSearchLoading, setIsProjectSearchLoading] = useState(false);
  const [isProjectSearchLoadingMore, setIsProjectSearchLoadingMore] = useState(false);
  const loadedProjectIdRef = useRef<string | null>(null);
  const loadedSidebarWorkspaceSurfaceRef = useRef<string | null>(null);
  const autoSelectedProjectIdRef = useRef<string | null>(null);
  const projectSearchRequestRef = useRef(0);
  const projectSearchDebounceRef = useRef<number | null>(null);
  const clearProjectSearchState = useCallback(() => {
    setProjectSearchResults([]);
    setProjectSearchTotal(0);
    setProjectSearchPage(0);
    setProjectSearchQuery('');
    setIsProjectSearchLoading(false);
    setIsProjectSearchLoadingMore(false);
    projectSearchRequestRef.current += 1;
    if (projectSearchDebounceRef.current) {
      window.clearTimeout(projectSearchDebounceRef.current);
      projectSearchDebounceRef.current = null;
    }
  }, []);

  // Use controlled or internal state
  const collapsed = controlledCollapsed !== undefined ? controlledCollapsed : internalCollapsed;
  const setCollapsed = useCallback(
    (value: boolean) => {
      if (controlledCollapsed === undefined) {
        setInternalCollapsed(value);
      }
      onCollapsedChange?.(value);
    },
    [controlledCollapsed, onCollapsedChange]
  );

  const {
    activeConversationId,
    setActiveConversation,
    loadConversations,
    loadMoreConversations,
    createNewConversation,
    deleteConversation,
  } = useAgentV3Store(
    useShallow((state) => ({
      activeConversationId: state.activeConversationId,
      setActiveConversation: state.setActiveConversation,
      loadConversations: state.loadConversations,
      loadMoreConversations: state.loadMoreConversations,
      createNewConversation: state.createNewConversation,
      deleteConversation: state.deleteConversation,
    }))
  );
  const currentWorkspace = useCurrentWorkspace();
  const workspaceTasks = useWorkspaceTasks();
  const workspaces = useWorkspaces();
  const { loadWorkspaceSurface } = useWorkspaceActions();

  const {
    conversations,
    conversationsLoading,
    hasMoreConversations,
    reset: resetConversations,
  } = useConversationsStore(
    useShallow((state) => ({
      conversations: state.conversations,
      conversationsLoading: state.conversationsLoading,
      hasMoreConversations: state.hasMoreConversations,
      reset: state.reset,
    }))
  );

  const { projects, currentProject, listProjects, setCurrentProject } = useProjectStore(
    useShallow((state) => ({
      projects: state.projects,
      currentProject: state.currentProject,
      listProjects: state.listProjects,
      setCurrentProject: state.setCurrentProject,
    }))
  );
  const preferredWorkspaceId = currentWorkspace?.id ?? workspaces[0]?.id ?? null;
  const normalizedTenantId = tenantId?.trim() ?? '';
  const resolvedTenantId = normalizedTenantId || undefined;
  const tenantScopedProjects = useMemo(
    () =>
      resolvedTenantId
        ? projects.filter((project) => project.tenant_id === resolvedTenantId)
        : projects,
    [projects, resolvedTenantId]
  );
  const projectSwitcherSourceProjects = useMemo(() => {
    const sourceProjects = [...tenantScopedProjects, ...projectSearchResults];
    if (projectBelongsToTenant(selectedProject, resolvedTenantId)) {
      sourceProjects.push(selectedProject);
    }
    if (currentProject && (!resolvedTenantId || currentProject.tenant_id === resolvedTenantId)) {
      sourceProjects.push(currentProject);
    }
    return sourceProjects;
  }, [
    currentProject,
    projectSearchResults,
    resolvedTenantId,
    selectedProject,
    tenantScopedProjects,
  ]);
  const uniqueProjects = useMemo(() => {
    const seenProjectIds = new Set<string>();
    return projectSwitcherSourceProjects.filter((project) => {
      if (seenProjectIds.has(project.id)) {
        return false;
      }
      seenProjectIds.add(project.id);
      return true;
    });
  }, [projectSwitcherSourceProjects]);
  const projectById = useMemo(
    () => new Map(uniqueProjects.map((project) => [project.id, project])),
    [uniqueProjects]
  );
  const defaultSelectableProjects = useMemo(() => {
    const seenProjectIds = new Set<string>();
    const limitedProjects: Project[] = [];
    const addProject = (project: Project | null | undefined) => {
      if (!project || seenProjectIds.has(project.id)) {
        return;
      }
      seenProjectIds.add(project.id);
      limitedProjects.push(project);
    };

    addProject(selectedProjectId ? projectById.get(selectedProjectId) : null);
    if (projectBelongsToTenant(currentProject, resolvedTenantId)) {
      addProject(currentProject);
    }

    for (const project of uniqueProjects) {
      if (limitedProjects.length >= PROJECT_SWITCHER_PAGE_SIZE) {
        break;
      }
      addProject(project);
    }

    return limitedProjects;
  }, [currentProject, projectById, resolvedTenantId, selectedProjectId, uniqueProjects]);
  const selectableProjects = useMemo(() => {
    if (!projectSearchQuery.trim()) {
      return defaultSelectableProjects;
    }

    const sourceProjects: Project[] = [];
    const scopedCurrentProject = currentProject;
    if (projectBelongsToTenant(scopedCurrentProject, resolvedTenantId)) {
      sourceProjects.push(scopedCurrentProject);
    }
    for (const project of projectSearchResults) {
      sourceProjects.push(project);
    }

    const seenProjectIds = new Set<string>();
    return sourceProjects.filter((project) => {
      if (seenProjectIds.has(project.id)) {
        return false;
      }
      seenProjectIds.add(project.id);
      return true;
    });
  }, [
    currentProject,
    defaultSelectableProjects,
    projectSearchQuery,
    projectSearchResults,
    resolvedTenantId,
  ]);
  const hasProjectSearchQuery = projectSearchQuery.trim().length > 0;
  const hasProjectSearchResults = projectSearchResults.length > 0;
  const showProjectSearchEmpty =
    hasProjectSearchQuery &&
    !isProjectSearchLoading &&
    projectSearchPage > 0 &&
    projectSearchTotal === 0;
  const tenantBasePath = normalizedTenantId ? `/tenant/${normalizedTenantId}` : '/tenant';
  const isAgentWorkspaceRoute =
    location.pathname === `${tenantBasePath}/agent-workspace` ||
    location.pathname.startsWith(`${tenantBasePath}/agent-workspace/`);
  const queryProjectId = useMemo(
    () => new URLSearchParams(location.search).get('projectId'),
    [location.search]
  );
  const workspaceIdFromQuery = useMemo(() => {
    if (!location.search) return null;
    return new URLSearchParams(location.search).get('workspaceId');
  }, [location.search]);
  const routeConversationId = useMemo(() => {
    const marker = '/agent-workspace/';
    const markerIndex = location.pathname.indexOf(marker);
    if (markerIndex === -1) {
      return null;
    }
    const encodedId = location.pathname.slice(markerIndex + marker.length).split('/')[0];
    if (!encodedId) {
      return null;
    }
    try {
      return decodeURIComponent(encodedId);
    } catch {
      return encodedId;
    }
  }, [location.pathname]);
  const selectedConversationId = routeConversationId ?? activeConversationId;
  const isProjectScopedPath = location.pathname.includes('/project/');
  const contextualProjectId =
    isProjectScopedPath && projectBelongsToTenant(currentProject, resolvedTenantId)
      ? currentProject.id
      : undefined;
  const contextualProjectBasePath = contextualProjectId
    ? `${tenantBasePath}/project/${contextualProjectId}`
    : null;
  const contextualNavItems = useMemo(
    () =>
      getContextualTopNavItems({
        basePath: tenantBasePath,
        projectBasePath: contextualProjectBasePath,
        preferredWorkspaceId,
        t: (key, fallback) => (fallback ? t(key, fallback) : t(key)),
        tenantId: resolvedTenantId,
        projectId: contextualProjectId,
      }),
    [
      contextualProjectBasePath,
      contextualProjectId,
      preferredWorkspaceId,
      resolvedTenantId,
      t,
      tenantBasePath,
    ]
  );
  const contextualNavGroups = useMemo(
    () => groupTenantTopNavItems(contextualNavItems),
    [contextualNavItems]
  );
  const previousTenantIdRef = useRef<string | undefined>(resolvedTenantId);
  const storedManualProjectId = useMemo(
    () => readManualStoredProjectId(resolvedTenantId),
    [resolvedTenantId]
  );

  useEffect(() => {
    const tenantChanged = previousTenantIdRef.current !== resolvedTenantId;
    previousTenantIdRef.current = resolvedTenantId;
    setSelectedProjectId(null);
    setSelectedProject(null);
    autoSelectedProjectIdRef.current = null;
    clearProjectSearchState();
    loadedProjectIdRef.current = null;
    loadedSidebarWorkspaceSurfaceRef.current = null;
    if (tenantChanged) {
      resetConversations();
      setActiveConversation(null);
    }
  }, [clearProjectSearchState, resetConversations, resolvedTenantId, setActiveConversation]);

  useEffect(() => {
    if (isAgentWorkspaceRoute) {
      return;
    }

    loadedProjectIdRef.current = null;
    loadedSidebarWorkspaceSurfaceRef.current = null;
    autoSelectedProjectIdRef.current = null;
    clearProjectSearchState();
    if (selectedProjectId) {
      setSelectedProjectId(null);
    }
    if (selectedProject) {
      setSelectedProject(null);
    }
    resetConversations();
    setActiveConversation(null);
  }, [
    clearProjectSearchState,
    isAgentWorkspaceRoute,
    resetConversations,
    selectedProject,
    selectedProjectId,
    setActiveConversation,
  ]);

  useEffect(
    () => () => {
      if (projectSearchDebounceRef.current) {
        window.clearTimeout(projectSearchDebounceRef.current);
      }
      projectSearchRequestRef.current += 1;
    },
    []
  );

  // Sync ref with state when not dragging
  useEffect(() => {
    if (!isDragging) {
      widthRef.current = sidebarWidth;
    }
  }, [sidebarWidth, isDragging]);

  // Keep the project switcher usable on every tenant page without loading the full project list.
  useEffect(() => {
    if (resolvedTenantId && tenantScopedProjects.length === 0) {
      void Promise.resolve(
        listProjects(resolvedTenantId, { page: 1, page_size: PROJECT_SWITCHER_PAGE_SIZE })
      ).catch((error: unknown) => {
        console.error('Failed to load projects:', error);
      });
    }
  }, [listProjects, resolvedTenantId, tenantScopedProjects.length]);

  // Set default selected project
  useEffect(() => {
    if (!isAgentWorkspaceRoute) {
      return;
    }

    if (queryProjectId) {
      const project = projectById.get(queryProjectId);
      if (!project) {
        return;
      }
      if (selectedProjectId === queryProjectId) {
        return;
      }
      autoSelectedProjectIdRef.current = null;
      setSelectedProjectId(queryProjectId);
      persistLastProjectId(resolvedTenantId, queryProjectId);
      setSelectedProject(project);
      setCurrentProject(project);
    } else if (
      uniqueProjects.length > 0 &&
      (!selectedProjectId || selectedProjectId === autoSelectedProjectIdRef.current)
    ) {
      const project =
        (storedManualProjectId ? projectById.get(storedManualProjectId) : undefined) ??
        (currentProject ? projectById.get(currentProject.id) : undefined) ??
        uniqueProjects[0];
      if (!project) return;
      if (selectedProjectId === project.id) {
        return;
      }
      autoSelectedProjectIdRef.current = project.id;
      setSelectedProjectId(project.id);
      setSelectedProject(project);
      setCurrentProject(project);
    }
  }, [
    currentProject,
    isAgentWorkspaceRoute,
    projectById,
    queryProjectId,
    resolvedTenantId,
    selectedProjectId,
    setCurrentProject,
    storedManualProjectId,
    uniqueProjects,
  ]);

  // Load conversations when selected project changes
  // NOTE: Use ref pattern to avoid dependency on loadConversations function
  // which gets recreated on every store update, causing infinite loops
  const loadConversationsRef = useRef(loadConversations);
  loadConversationsRef.current = loadConversations;

  useEffect(() => {
    if (
      isAgentWorkspaceRoute &&
      selectedProjectId &&
      loadedProjectIdRef.current !== selectedProjectId
    ) {
      const controller = new AbortController();
      if (loadedProjectIdRef.current) {
        resetConversations();
        setActiveConversation(null);
      }
      loadedProjectIdRef.current = selectedProjectId;
      // Use ref to call latest function without triggering effect re-run
      void Promise.resolve(
        loadConversationsRef.current(selectedProjectId, controller.signal)
      ).catch((error: unknown) => {
        if (controller.signal.aborted || (error as { name?: string }).name === 'CanceledError') {
          return;
        }
        console.error('Failed to load conversations:', error);
      });
      return () => {
        controller.abort();
      };
    }
    // ONLY depend on selectedProjectId, NOT loadConversations
    return undefined;
  }, [isAgentWorkspaceRoute, resetConversations, selectedProjectId, setActiveConversation]);

  useEffect(() => {
    if (!isAgentWorkspaceRoute || !tenantId || !selectedProjectId || !workspaceIdFromQuery) {
      return;
    }

    const hasWorkspaceTitle =
      currentWorkspace?.id === workspaceIdFromQuery ||
      workspaces.some((workspace) => workspace.id === workspaceIdFromQuery);
    const hasTaskTitles = workspaceTasks.some((task) => task.workspace_id === workspaceIdFromQuery);
    if (hasWorkspaceTitle && hasTaskTitles) {
      return;
    }

    const loadKey = `${tenantId}:${selectedProjectId}:${workspaceIdFromQuery}`;
    if (loadedSidebarWorkspaceSurfaceRef.current === loadKey) {
      return;
    }
    loadedSidebarWorkspaceSurfaceRef.current = loadKey;

    void Promise.resolve(
      loadWorkspaceSurface(tenantId, selectedProjectId, workspaceIdFromQuery)
    ).catch((error: unknown) => {
      loadedSidebarWorkspaceSurfaceRef.current = null;
      console.error('Failed to load workspace context for conversations:', error);
    });
  }, [
    currentWorkspace?.id,
    isAgentWorkspaceRoute,
    loadWorkspaceSurface,
    selectedProjectId,
    tenantId,
    workspaceIdFromQuery,
    workspaceTasks,
    workspaces,
  ]);

  // Enrich conversations with project info
  const visibleConversations = useMemo(
    () =>
      isAgentWorkspaceRoute && selectedProjectId
        ? conversations.filter((conversation) =>
            conversationBelongsToProject(conversation, selectedProjectId)
          )
        : [],
    [conversations, isAgentWorkspaceRoute, selectedProjectId]
  );
  const selectedProjectName = useMemo(
    () => projectById.get(selectedProjectId ?? '')?.name || 'Unknown Project',
    [projectById, selectedProjectId]
  );
  const emptyProjectOptionLabel = isProjectSearchLoading
    ? t('agent.sidebar.searchingProjects', 'Searching projects...')
    : isAgentWorkspaceRoute || projectSearchQuery.trim()
      ? t('agent.sidebar.noProjectsFound', 'No projects found')
      : t('agent.sidebar.searchProjectsToSelect', 'Search to select a project');

  const enrichedConversations: ConversationWithProject[] = useMemo(() => {
    const workspaceNameById = new Map(
      workspaces.map((workspace) => [workspace.id, workspace.name])
    );
    if (currentWorkspace) {
      workspaceNameById.set(currentWorkspace.id, currentWorkspace.name);
    }
    const workspaceTaskTitleById = new Map(workspaceTasks.map((task) => [task.id, task.title]));
    return visibleConversations
      .filter((conv) => !isDerivedAgentConversation(conv))
      .map((conv) => ({
        ...conv,
        projectId: selectedProjectId || '',
        projectName: selectedProjectName,
        workspaceTaskTitle: (() => {
          const taskId = workspaceNodeIdFromConversation(conv);
          return taskId ? (workspaceTaskTitleById.get(taskId) ?? null) : null;
        })(),
        workspaceName: (() => {
          const workspaceId = workspaceIdFromConversation(conv);
          return (
            conv.workspace_name ??
            (workspaceId ? (workspaceNameById.get(workspaceId) ?? null) : null)
          );
        })(),
      }));
  }, [
    currentWorkspace,
    selectedProjectId,
    selectedProjectName,
    visibleConversations,
    workspaceTasks,
    workspaces,
  ]);
  const conversationSections = useMemo(
    () => buildConversationSections(enrichedConversations, t),
    [enrichedConversations, t]
  );
  const workspaceGroupIdsKey = useMemo(
    () =>
      JSON.stringify(
        conversationSections
          .filter((section) => section.type === 'workspace')
          .map((section) => section.id)
      ),
    [conversationSections]
  );
  const [collapsedGroupIds, setCollapsedGroupIds] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    const validGroupIds = new Set(JSON.parse(workspaceGroupIdsKey) as string[]);
    setCollapsedGroupIds((current) => {
      const next = new Set(Array.from(current).filter((groupId) => validGroupIds.has(groupId)));
      return next.size === current.size ? current : next;
    });
  }, [workspaceGroupIdsKey]);

  const toggleConversationGroup = useCallback((groupId: string) => {
    setCollapsedGroupIds((current) => {
      const next = new Set(current);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  }, []);

  const isLoadingMoreRef = useRef(false);
  const autoFillProjectIdRef = useRef<string | null>(null);
  const autoFillLoadCountRef = useRef(0);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const loadMore = useCallback(async () => {
    if (!hasMoreConversations || isLoadingMoreRef.current || !selectedProjectId) return;

    isLoadingMoreRef.current = true;
    setIsLoadingMore(true);
    try {
      await loadMoreConversations(selectedProjectId);
    } finally {
      isLoadingMoreRef.current = false;
      setIsLoadingMore(false);
    }
  }, [hasMoreConversations, selectedProjectId, loadMoreConversations]);

  const handleConversationScroll = useCallback(
    (e: React.UIEvent<HTMLDivElement>) => {
      if (!hasMoreConversations || isLoadingMoreRef.current || !selectedProjectId) return;
      const target = e.currentTarget;
      const nearBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 100;
      if (nearBottom) {
        void loadMore().catch((error: unknown) => {
          console.error('Failed to load more conversations:', error);
        });
      }
    },
    [hasMoreConversations, selectedProjectId, loadMore]
  );

  useEffect(() => {
    autoFillProjectIdRef.current = selectedProjectId;
    autoFillLoadCountRef.current = 0;
  }, [selectedProjectId]);

  const handleSelectConversation = useCallback(
    (id: string, projectId: string) => {
      void navigate(
        buildAgentWorkspacePath({
          tenantId,
          conversationId: id,
          projectId,
          workspaceId: workspaceIdFromQuery,
        })
      );
    },
    [navigate, tenantId, workspaceIdFromQuery]
  );

  // Keep route-driven or distant conversation switches anchored to the selected item.
  useLayoutEffect(() => {
    const container = scrollContainerRef.current;
    const activeItem = activeConversationItemRef.current;
    if (!container || !activeItem || collapsed) {
      return;
    }

    const containerRect = container.getBoundingClientRect();
    const itemRect = activeItem.getBoundingClientRect();
    const isFullyVisible =
      itemRect.top >= containerRect.top && itemRect.bottom <= containerRect.bottom;
    if (isFullyVisible) {
      return;
    }

    const nextScrollTop =
      container.scrollTop +
      itemRect.top -
      containerRect.top -
      (container.clientHeight - activeItem.offsetHeight) / 2;
    container.scrollTop = Math.max(0, nextScrollTop);
  }, [collapsed, conversationSections, selectedConversationId]);

  // Auto-load more conversations when content doesn't fill the container
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (
      !isAgentWorkspaceRoute ||
      !container ||
      !hasMoreConversations ||
      isLoadingMore ||
      isLoadingMoreRef.current ||
      !selectedProjectId
    ) {
      return;
    }
    if (autoFillProjectIdRef.current !== selectedProjectId) {
      autoFillProjectIdRef.current = selectedProjectId;
      autoFillLoadCountRef.current = 0;
    }
    if (autoFillLoadCountRef.current >= CONVERSATION_AUTO_FILL_PAGE_LIMIT) {
      return;
    }

    // Check if content fills the container
    const contentFillsContainer = container.scrollHeight > container.clientHeight + 10;

    // If content doesn't fill container and there are more conversations, load more
    if (!contentFillsContainer && visibleConversations.length > 0) {
      autoFillLoadCountRef.current += 1;
      void loadMore().catch((error: unknown) => {
        console.error('Failed to auto-load more conversations:', error);
      });
    }
  }, [
    visibleConversations.length,
    hasMoreConversations,
    isAgentWorkspaceRoute,
    isLoadingMore,
    selectedProjectId,
    loadMore,
  ]);

  const handleNewConversation = useCallback(async () => {
    if (!selectedProjectId) return;
    const newId = await createNewConversation(selectedProjectId);
    if (newId) {
      void navigate(
        buildAgentWorkspacePath({
          tenantId,
          conversationId: newId,
          projectId: selectedProjectId,
        })
      );
    }
  }, [selectedProjectId, createNewConversation, navigate, tenantId]);

  const handleDeleteConversation = useCallback(
    (id: string, e: React.MouseEvent) => {
      e.stopPropagation();
      if (!selectedProjectId) return;
      const confirmed = window.confirm(
        `${t('agent.sidebar.deleteTitle', 'Delete Conversation')}\n\n${t(
          'agent.sidebar.deleteConfirm',
          'Are you sure? This action cannot be undone.'
        )}`
      );
      if (!confirmed) {
        return;
      }

      void (async () => {
        try {
          await deleteConversation(id, selectedProjectId);
          if (activeConversationId === id) {
            void navigate(
              buildAgentWorkspacePath({
                tenantId,
                projectId: selectedProjectId,
                workspaceId: workspaceIdFromQuery,
              })
            );
          }
        } catch (error) {
          console.error('Failed to delete conversation:', error);
        }
      })();
    },
    [
      selectedProjectId,
      activeConversationId,
      deleteConversation,
      navigate,
      tenantId,
      t,
      workspaceIdFromQuery,
    ]
  );

  // Rename conversation state and handlers
  const [renamingConversation, setRenamingConversation] = useState<ConversationWithProject | null>(
    null
  );
  const [newTitle, setNewTitle] = useState('');
  const [isRenaming, setIsRenaming] = useState(false);
  const renameConversation = useAgentV3Store((state) => state.renameConversation);

  const handleRenameClick = useCallback((conv: ConversationWithProject, e: React.MouseEvent) => {
    e.stopPropagation();
    setRenamingConversation(conv);
    setNewTitle(conv.title || '');
  }, []);

  const handleRenameSubmit = useCallback(async () => {
    if (!renamingConversation || !newTitle.trim() || !selectedProjectId) return;

    setIsRenaming(true);
    try {
      await renameConversation(renamingConversation.id, selectedProjectId, newTitle.trim());
      setRenamingConversation(null);
      setNewTitle('');
    } catch (error) {
      console.error('Failed to rename conversation:', error);
    } finally {
      setIsRenaming(false);
    }
  }, [renamingConversation, newTitle, selectedProjectId, renameConversation]);

  const handleRenameCancel = useCallback(() => {
    setRenamingConversation(null);
    setNewTitle('');
  }, []);

  const handleProjectChange = useCallback(
    (projectId: string) => {
      autoSelectedProjectIdRef.current = null;
      setSelectedProjectId(projectId);
      setProjectSearchQuery('');
      setProjectSearchResults([]);
      persistLastProjectId(resolvedTenantId, projectId);
      const project = projectById.get(projectId);
      if (project) {
        setSelectedProject(project);
        setCurrentProject(project);
      }
      void navigate(buildAgentWorkspacePath({ tenantId, projectId }));
      // NOTE: loadConversations is called by useEffect when selectedProjectId changes
      // Do NOT call it here to avoid duplicate requests
    },
    [navigate, projectById, resolvedTenantId, setCurrentProject, tenantId]
  );

  const handleProjectSearch = useCallback(
    (value: string) => {
      setProjectSearchQuery(value);
      setProjectSearchResults([]);
      setProjectSearchTotal(0);
      setProjectSearchPage(0);
      setIsProjectSearchLoadingMore(false);
      if (projectSearchDebounceRef.current) {
        window.clearTimeout(projectSearchDebounceRef.current);
        projectSearchDebounceRef.current = null;
      }

      const search = value.trim();
      const requestId = projectSearchRequestRef.current + 1;
      projectSearchRequestRef.current = requestId;

      if (!resolvedTenantId || !search) {
        setIsProjectSearchLoading(false);
        return;
      }

      setIsProjectSearchLoading(true);
      projectSearchDebounceRef.current = window.setTimeout(() => {
        void projectAPI
          .list(resolvedTenantId, {
            page: 1,
            page_size: PROJECT_SEARCH_PAGE_SIZE,
            search,
          })
          .then((response) => {
            if (projectSearchRequestRef.current !== requestId) {
              return;
            }
            setProjectSearchResults(response.projects);
            setProjectSearchTotal(response.total);
            setProjectSearchPage(response.page);
          })
          .catch((error: unknown) => {
            if (projectSearchRequestRef.current !== requestId) {
              return;
            }
            console.error('Failed to search projects:', error);
            setProjectSearchResults([]);
            setProjectSearchTotal(0);
            setProjectSearchPage(0);
          })
          .finally(() => {
            if (projectSearchRequestRef.current === requestId) {
              setIsProjectSearchLoading(false);
            }
          });
      }, PROJECT_SEARCH_DEBOUNCE_MS);
    },
    [resolvedTenantId]
  );

  const hasMoreProjectSearchResults =
    hasProjectSearchQuery && projectSearchResults.length < projectSearchTotal;

  const handleLoadMoreProjectSearchResults = useCallback(() => {
    const search = projectSearchQuery.trim();
    if (
      !resolvedTenantId ||
      !search ||
      isProjectSearchLoading ||
      isProjectSearchLoadingMore ||
      !hasMoreProjectSearchResults
    ) {
      return;
    }

    const requestId = projectSearchRequestRef.current + 1;
    projectSearchRequestRef.current = requestId;
    const nextPage = projectSearchPage + 1;
    setIsProjectSearchLoadingMore(true);

    void projectAPI
      .list(resolvedTenantId, {
        page: nextPage,
        page_size: PROJECT_SEARCH_PAGE_SIZE,
        search,
      })
      .then((response) => {
        if (projectSearchRequestRef.current !== requestId) {
          return;
        }

        setProjectSearchResults((currentResults) => {
          const seenProjectIds = new Set(currentResults.map((project) => project.id));
          const nextProjects = response.projects.filter((project) => {
            if (seenProjectIds.has(project.id)) {
              return false;
            }
            seenProjectIds.add(project.id);
            return true;
          });
          return [...currentResults, ...nextProjects];
        });
        setProjectSearchTotal(response.total);
        setProjectSearchPage(response.page);
      })
      .catch((error: unknown) => {
        if (projectSearchRequestRef.current !== requestId) {
          return;
        }
        console.error('Failed to load more projects:', error);
      })
      .finally(() => {
        if (projectSearchRequestRef.current === requestId) {
          setIsProjectSearchLoadingMore(false);
        }
      });
  }, [
    hasMoreProjectSearchResults,
    isProjectSearchLoading,
    isProjectSearchLoadingMore,
    projectSearchPage,
    projectSearchQuery,
    resolvedTenantId,
  ]);

  // Get current width for render
  const currentWidth = collapsed ? SIDEBAR_COLLAPSED_WIDTH : sidebarWidth;
  const conversationCountLabel = t('agent.sidebar.conversationCount', {
    count: visibleConversations.length,
    defaultValue: '{{count}} conversations',
  });
  const conversationCountText =
    typeof conversationCountLabel === 'string'
      ? conversationCountLabel
      : `${visibleConversations.length.toString()} ${t(
          'agent.sidebar.conversations',
          'conversations'
        )}`;
  const projectSearchCountLabel = t('agent.sidebar.projectSearchCount', {
    count: projectSearchResults.length,
    total: projectSearchTotal,
    defaultValue: 'Showing {{count}} of {{total}} projects',
  });
  const projectSearchCountText =
    typeof projectSearchCountLabel === 'string'
      ? projectSearchCountLabel
      : `${projectSearchResults.length.toString()} / ${projectSearchTotal.toString()}`;
  const projectSearchResultsLabel = t(
    'agent.sidebar.projectSearchResults',
    'Authorized project search results'
  );
  const selectedProjectBadge = t('agent.sidebar.selectedProjectBadge', 'Selected');

  return (
    <aside
      ref={sidebarRef}
      className={`
        ${mobile ? 'flex' : 'hidden md:flex'}
        flex-col bg-surface-light dark:bg-surface-dark border-r border-slate-200 dark:border-border-dark 
        flex-none z-20 h-full relative
        ${isDragging ? '' : 'transition-[color,background-color,border-color,box-shadow,opacity,transform,width] duration-300 ease-in-out'}
      `}
      style={{ width: mobile ? '100%' : currentWidth }}
    >
      {/* Resize Handle - only show when not collapsed */}
      {!collapsed && !mobile && (
        <Resizer
          direction="horizontal"
          currentSize={sidebarWidth}
          minSize={SIDEBAR_MIN_WIDTH}
          maxSize={SIDEBAR_MAX_WIDTH}
          onResize={(newWidth) => {
            setIsDragging(true);
            setSidebarWidth(newWidth);
            widthRef.current = newWidth;
            if (sidebarRef.current) {
              sidebarRef.current.style.width = `${String(newWidth)}px`;
            }
          }}
          onResizeEnd={(finalSize) => {
            if (finalSize < COLLAPSE_THRESHOLD) {
              setCollapsed(true);
              setSidebarWidth(SIDEBAR_DEFAULT_WIDTH);
              widthRef.current = SIDEBAR_DEFAULT_WIDTH;
              if (sidebarRef.current) {
                sidebarRef.current.style.width = `${String(SIDEBAR_COLLAPSED_WIDTH)}px`;
              }
            } else {
              setCollapsed(false);
              setSidebarWidth(finalSize);
              widthRef.current = finalSize;
            }
            setIsDragging(false);
          }}
          position="right"
        />
      )}

      {/* Header */}
      <div
        className={`
        h-16 flex items-center px-4 border-b border-slate-100 dark:border-slate-800/50 shrink-0
        ${collapsed ? 'justify-center' : ''}
      `}
      >
        {collapsed ? (
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
            <Bot className="text-primary" size={24} />
          </div>
        ) : (
          <div className="flex items-center gap-3 w-full min-w-0">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-900 dark:bg-slate-100">
              <Bot className="text-slate-50 dark:text-slate-900" size={24} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-semibold text-slate-900 dark:text-slate-100 truncate text-sm">
                {t('agent.sidebar.workspaceTitle', 'Agent Workspace')}
              </div>
              <p className="text-xs text-slate-500">{conversationCountText}</p>
            </div>
          </div>
        )}
      </div>

      {/* Project Selector */}
      {!collapsed && (
        <div className="space-y-2 border-b border-slate-100 p-3 dark:border-slate-800/50">
          <div className="relative">
            <select
              aria-label={t('agent.sidebar.projectSwitcher', 'Project switcher')}
              value={selectedProjectId ?? ''}
              onChange={(event) => {
                if (event.target.value) {
                  handleProjectChange(event.target.value);
                }
              }}
              disabled={!resolvedTenantId || selectableProjects.length === 0}
              className="h-9 w-full appearance-none rounded-md border border-slate-200 bg-white px-3 pr-8 text-sm text-slate-900 outline-none transition-colors hover:border-slate-300 focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:border-slate-600"
            >
              {selectableProjects.length === 0 ? (
                <option value="">{emptyProjectOptionLabel}</option>
              ) : (
                <>
                  {!selectedProjectId ? (
                    <option value="">
                      {t('agent.sidebar.selectProjectTitle', 'Select Project')}
                    </option>
                  ) : null}
                  {selectableProjects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </>
              )}
            </select>
            <ChevronDown
              size={16}
              className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400"
            />
          </div>
          <div className="relative">
            <LazyInput
              aria-label={t('agent.sidebar.searchProjects', 'Search projects')}
              className="w-full"
              placeholder={t(
                'agent.sidebar.searchProjectsPlaceholder',
                'Search all authorized projects'
              )}
              value={projectSearchQuery}
              onChange={(event: React.ChangeEvent<HTMLInputElement>) => {
                handleProjectSearch(event.target.value);
              }}
            />
            {isProjectSearchLoading ? (
              <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-slate-400">
                {t('agent.sidebar.searchingProjects', 'Searching projects...')}
              </span>
            ) : null}
          </div>
          {hasProjectSearchQuery && hasProjectSearchResults ? (
            <div
              role="list"
              aria-label={projectSearchResultsLabel}
              className="max-h-44 overflow-y-auto rounded-md border border-slate-200 bg-white p-1 shadow-sm dark:border-slate-700 dark:bg-slate-900"
            >
              {projectSearchResults.map((project) => {
                const isSelectedProject = selectedProjectId === project.id;
                return (
                  <div key={project.id} role="listitem">
                    <button
                      type="button"
                      aria-current={isSelectedProject ? 'true' : undefined}
                      className="flex min-h-8 w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-sm text-slate-700 transition-colors hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-primary/20 dark:text-slate-200 dark:hover:bg-slate-800"
                      onClick={() => {
                        handleProjectChange(project.id);
                      }}
                    >
                      <span className="truncate">{project.name}</span>
                      {isSelectedProject ? (
                        <span
                          aria-hidden="true"
                          className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary"
                        >
                          {selectedProjectBadge}
                        </span>
                      ) : null}
                    </button>
                  </div>
                );
              })}
            </div>
          ) : null}
          {showProjectSearchEmpty ? (
            <div className="rounded-md border border-dashed border-slate-200 px-3 py-2 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
              {t('agent.sidebar.noProjectsFound', 'No projects found')}
            </div>
          ) : null}
          {hasProjectSearchQuery && projectSearchTotal > 0 ? (
            <div className="flex items-center justify-between gap-2 text-xs text-slate-500 dark:text-slate-400">
              <span>{projectSearchCountText}</span>
              {hasMoreProjectSearchResults ? (
                <button
                  type="button"
                  className="inline-flex h-7 items-center gap-1 rounded-md border border-slate-200 px-2 text-xs font-medium text-slate-700 transition-colors hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400 dark:border-slate-700 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:bg-slate-800"
                  disabled={isProjectSearchLoading || isProjectSearchLoadingMore}
                  onClick={handleLoadMoreProjectSearchResults}
                >
                  <ChevronDown
                    size={14}
                    className={
                      isProjectSearchLoadingMore ? 'animate-spin motion-reduce:animate-none' : ''
                    }
                    aria-hidden="true"
                  />
                  {isProjectSearchLoadingMore
                    ? t('agent.sidebar.loadingMoreProjects', 'Loading...')
                    : t('agent.sidebar.loadMoreProjects', 'Load more')}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      )}

      {/* Collapsed Project Indicator */}
      {collapsed && selectedProjectId && (
        <div className="px-2 pb-2 flex justify-center">
          <Tooltip
            title={
              projectById.get(selectedProjectId)?.name ||
              t('agent.sidebar.selectProjectTitle', 'Select Project')
            }
          >
            <button
              type="button"
              onClick={() => {
                setCollapsed(false);
              }}
              aria-label={t('agent.sidebar.expandProjectSidebar', {
                project:
                  projectById.get(selectedProjectId)?.name ||
                  t('agent.sidebar.selectProjectTitle', 'Select Project'),
                defaultValue: 'Expand project sidebar for {{project}}',
              })}
              title={t('agent.sidebar.expandProjectSidebar', {
                project:
                  projectById.get(selectedProjectId)?.name ||
                  t('agent.sidebar.selectProjectTitle', 'Select Project'),
                defaultValue: 'Expand project sidebar for {{project}}',
              })}
              className="w-10 h-10 rounded-xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
            >
              <FolderOpen size={20} className="text-slate-500" />
            </button>
          </Tooltip>
        </div>
      )}

      {/* New Chat Button */}
      <div className={collapsed ? 'px-2 flex justify-center' : 'p-3'}>
        <LazyButton
          type="primary"
          icon={<Plus size={collapsed ? 20 : 18} />}
          onClick={handleNewConversation}
          disabled={!isAgentWorkspaceRoute || !selectedProjectId}
          className={`
            ${collapsed ? 'w-10 h-10 p-0' : 'w-full h-10'}
            bg-primary hover:bg-primary-600 shadow-sm
            rounded-xl flex items-center justify-center gap-2
          `}
        >
          {!collapsed && <span>{t('agent.sidebar.newChat', 'New Chat')}</span>}
        </LazyButton>
      </div>

      {/* Conversation List */}
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto custom-scrollbar"
        onScroll={handleConversationScroll}
      >
        {!collapsed && (
          <div className="px-3">
            {conversationsLoading ? (
              <div className="flex items-center justify-center py-8">
                <div className="w-5 h-5 border-2 border-primary/20 border-t-primary rounded-full animate-spin motion-reduce:animate-none" />
              </div>
            ) : (
              <>
                {enrichedConversations.length === 0 ? (
                  <div className="text-center py-8 text-slate-400">
                    <MessageSquare size={32} className="mx-auto mb-2 opacity-50" />
                    <p className="text-xs">
                      {selectedProjectId
                        ? t('agent.sidebar.noConversations', 'No conversations yet')
                        : t(
                            'agent.sidebar.selectProjectToViewConversations',
                            'Select a project to view conversations'
                          )}
                    </p>
                  </div>
                ) : (
                  conversationSections.map((section) => {
                    if (section.type === 'conversation') {
                      const conv = section.conversation;
                      return (
                        <ConversationItem
                          activeItemRef={
                            conv.id === selectedConversationId
                              ? activeConversationItemRef
                              : undefined
                          }
                          key={conv.id}
                          conversation={conv}
                          isActive={conv.id === selectedConversationId}
                          onSelect={() => {
                            handleSelectConversation(conv.id, conv.projectId);
                          }}
                          onDelete={(e) => {
                            handleDeleteConversation(conv.id, e);
                          }}
                          onRename={(e) => {
                            handleRenameClick(conv, e);
                          }}
                        />
                      );
                    }

                    const groupCollapsed = collapsedGroupIds.has(section.id);
                    return (
                      <section key={section.id} aria-label={section.workspaceTitle}>
                        <ConversationGroupHeader
                          collapsed={groupCollapsed}
                          conversationCount={section.conversations.length}
                          onToggle={() => {
                            toggleConversationGroup(section.id);
                          }}
                          workspaceTitle={section.workspaceTitle}
                        />
                        {!groupCollapsed
                          ? section.conversations.map((conv) => (
                              <ConversationItem
                                activeItemRef={
                                  conv.id === selectedConversationId
                                    ? activeConversationItemRef
                                    : undefined
                                }
                                key={conv.id}
                                conversation={conv}
                                grouped
                                isActive={conv.id === selectedConversationId}
                                onSelect={() => {
                                  handleSelectConversation(conv.id, conv.projectId);
                                }}
                                onDelete={(e) => {
                                  handleDeleteConversation(conv.id, e);
                                }}
                                onRename={(e) => {
                                  handleRenameClick(conv, e);
                                }}
                              />
                            ))
                          : null}
                      </section>
                    );
                  })
                )}
                {isLoadingMore && (
                  <div className="flex items-center justify-center py-3">
                    <div className="w-4 h-4 border-2 border-primary/20 border-t-primary rounded-full animate-spin motion-reduce:animate-none" />
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* Mobile Navigation Links - shown only in mobile drawer */}
      {mobile && tenantId && contextualNavItems.length > 0 && (
        <div className="border-t border-slate-100 dark:border-slate-800/50 px-3 py-2">
          <p className="text-2xs font-semibold text-slate-400 uppercase tracking-wider px-2 mb-1">
            {t('nav.navigation', 'Navigation')}
          </p>
          {contextualNavGroups.map((group) => (
            <div key={group.id} className="py-1">
              {group.label ? (
                <p className="px-2 pb-1 pt-2 text-2xs font-semibold uppercase tracking-wider text-slate-400">
                  {group.label}
                </p>
              ) : null}
              {group.items.map((item) => (
                <NavLink
                  key={item.id}
                  to={item.path}
                  className={() =>
                    `flex items-center gap-2.5 px-2 py-2 rounded-lg text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset ${
                      isContextualTopNavItemActive(location.pathname, item)
                        ? 'bg-primary/10 text-primary font-medium'
                        : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
                    }`
                  }
                >
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </div>
      )}

      {renamingConversation ? (
        <div className="absolute inset-x-3 bottom-3 z-20 rounded-lg border border-slate-200 bg-white p-3 shadow-lg dark:border-slate-700 dark:bg-slate-900">
          <div role="dialog" aria-modal="true" aria-labelledby="tenant-sidebar-rename-title">
            <h2
              id="tenant-sidebar-rename-title"
              className="text-sm font-semibold text-slate-900 dark:text-slate-100"
            >
              {t('agent.sidebar.renameTitle', 'Rename Conversation')}
            </h2>
            <LazyInput
              className="mt-3"
              placeholder={t('agent.sidebar.renamePlaceholder', 'Enter conversation title')}
              value={newTitle}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                setNewTitle(e.target.value);
              }}
              onPressEnter={handleRenameSubmit}
              autoFocus
            />
            <div className="mt-3 flex justify-end gap-2">
              <LazyButton size="small" onClick={handleRenameCancel}>
                {t('common.cancel', 'Cancel')}
              </LazyButton>
              <LazyButton
                size="small"
                type="primary"
                loading={isRenaming}
                disabled={!newTitle.trim()}
                onClick={() => {
                  void handleRenameSubmit();
                }}
              >
                {t('agent.sidebar.rename', 'Rename')}
              </LazyButton>
            </div>
          </div>
        </div>
      ) : null}
    </aside>
  );
};

export default TenantChatSidebar;
