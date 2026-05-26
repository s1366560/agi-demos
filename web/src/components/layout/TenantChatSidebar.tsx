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

import { Modal } from 'antd';
import {
  Plus,
  MessageSquare,
  MoreVertical,
  Trash2,
  Edit3,
  Bot,
  FolderOpen,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useConversationsStore } from '@/stores/agent/conversationsStore';
import { useIsLoadingHistory } from '@/stores/agent/timelineStore';
import { useAgentV3Store } from '@/stores/agentV3';
import { useProjectStore } from '@/stores/project';
import {
  useCurrentWorkspace,
  useWorkspaceActions,
  useWorkspaceTasks,
  useWorkspaces,
} from '@/stores/workspace';

import { buildAgentWorkspacePath } from '@/utils/agentWorkspacePath';
import { formatDistanceToNow } from '@/utils/date';

import {
  getContextualTopNavItems,
  isContextualTopNavItemActive,
} from '@/components/layout/TenantHeader';
import { LazyButton, LazyDropdown, LazySelect, LazyInput } from '@/components/ui/lazyAntd';

import { Resizer } from '../agent/Resizer';

import type { Conversation } from '@/types/agent';

import type { MenuProps } from 'antd';

interface ConversationWithProject extends Conversation {
  projectId: string;
  projectName: string;
  workspaceTaskTitle?: string | null | undefined;
  workspaceName?: string | null | undefined;
}

interface ConversationItemProps {
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
      workspaceTitle: string;
      conversations: ConversationWithProject[];
    };

// Constants for resize constraints
const SIDEBAR_MIN_WIDTH = 200;
const SIDEBAR_MAX_WIDTH = 400;
const SIDEBAR_DEFAULT_WIDTH = 256;
const SIDEBAR_COLLAPSED_WIDTH = 80;
const COLLAPSE_THRESHOLD = 120; // Width below which sidebar collapses

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
  const workspaceSectionIndex = new Map<string, number>();

  for (const conversation of conversations) {
    const display = buildConversationDisplay(conversation, t, '');
    if (!display.isWorkspaceConversation) {
      sections.push({ type: 'conversation', conversation });
      continue;
    }

    const workspaceKey = workspaceIdFromConversation(conversation) ?? display.contextLabel;
    const sectionId = `workspace:${workspaceKey}`;
    const existingIndex = workspaceSectionIndex.get(sectionId);

    if (existingIndex !== undefined) {
      const section = sections[existingIndex];
      if (section?.type === 'workspace') {
        section.conversations.push(conversation);
      }
      continue;
    }

    workspaceSectionIndex.set(sectionId, sections.length);
    sections.push({
      type: 'workspace',
      id: sectionId,
      workspaceTitle: display.contextLabel,
      conversations: [conversation],
    });
  }

  return sections;
}

// Memoized ConversationItem to prevent unnecessary re-renders (rerender-memo)
const ConversationItem: React.FC<ConversationItemProps> = memo(
  ({ conversation, grouped = false, isActive, onSelect, onDelete, onRename }) => {
    const { t } = useTranslation();
    const timeAgo = React.useMemo(() => {
      try {
        return formatDistanceToNow(conversation.created_at);
      } catch {
        return '';
      }
    }, [conversation.created_at]);

    const handleMenuClick: MenuProps['onClick'] = ({ key }) => {
      if (key === 'delete') {
        onDelete({} as React.MouseEvent);
      } else if (key === 'rename') {
        onRename?.({} as React.MouseEvent);
      }
    };

    const items: MenuProps['items'] = React.useMemo(
      () => [
        {
          key: 'rename',
          icon: <Edit3 size={14} />,
          label: t('agent.sidebar.rename', 'Rename'),
          onClick: () => onRename?.({} as React.MouseEvent),
        },
        {
          key: 'delete',
          icon: <Trash2 size={14} />,
          label: t('agent.sidebar.delete', 'Delete'),
          danger: true,
          onClick: (e) => {
            onDelete(e.domEvent as React.MouseEvent);
          },
        },
      ],
      [onDelete, onRename, t]
    );
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
          <LazyDropdown
            menu={{ items, onClick: handleMenuClick }}
            trigger={['click']}
            placement="bottomRight"
          >
            <LazyButton
              type="text"
              size="small"
              icon={<MoreVertical size={14} />}
              className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
              onClick={(e: React.MouseEvent) => {
                e.stopPropagation();
              }}
            />
          </LazyDropdown>
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

  // Internal state for uncontrolled mode
  const [internalCollapsed, setInternalCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT_WIDTH);
  const [isDragging, setIsDragging] = useState(false);

  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

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
    loadConversations,
    loadMoreConversations,
    createNewConversation,
    deleteConversation,
  } = useAgentV3Store(
    useShallow((state) => ({
      activeConversationId: state.activeConversationId,
      loadConversations: state.loadConversations,
      loadMoreConversations: state.loadMoreConversations,
      createNewConversation: state.createNewConversation,
      deleteConversation: state.deleteConversation,
    }))
  );
  const isLoadingHistory = useIsLoadingHistory();
  const currentWorkspace = useCurrentWorkspace();
  const workspaceTasks = useWorkspaceTasks();
  const workspaces = useWorkspaces();
  const { loadWorkspaceSurface } = useWorkspaceActions();

  const { conversations, hasMoreConversations } = useConversationsStore(
    useShallow((state) => ({
      conversations: state.conversations,
      hasMoreConversations: state.hasMoreConversations,
    }))
  );

  const { projects, currentProject, listProjects, setCurrentProject } = useProjectStore();
  const preferredWorkspaceId = currentWorkspace?.id ?? workspaces[0]?.id ?? null;
  const normalizedTenantId = tenantId?.trim() ?? '';
  const resolvedTenantId = normalizedTenantId || undefined;
  const tenantBasePath = normalizedTenantId ? `/tenant/${normalizedTenantId}` : '/tenant';
  const queryProjectId = useMemo(
    () => new URLSearchParams(location.search).get('projectId'),
    [location.search]
  );
  const workspaceIdFromQuery = useMemo(() => {
    if (!location.search) return null;
    return new URLSearchParams(location.search).get('workspaceId');
  }, [location.search]);
  const isProjectScopedPath = location.pathname.includes('/project/');
  const contextualProjectId = isProjectScopedPath ? currentProject?.id : undefined;
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

  // Sync ref with state when not dragging
  useEffect(() => {
    if (!isDragging) {
      widthRef.current = sidebarWidth;
    }
  }, [sidebarWidth, isDragging]);

  // Load projects on mount
  useEffect(() => {
    if (tenantId && projects.length === 0) {
      void Promise.resolve(listProjects(tenantId)).catch((error: unknown) => {
        console.error('Failed to load projects:', error);
      });
    }
  }, [tenantId, projects.length, listProjects]);

  // Set default selected project
  useEffect(() => {
    if (queryProjectId && selectedProjectId !== queryProjectId) {
      setSelectedProjectId(queryProjectId);
      localStorage.setItem('agent:lastProjectId', queryProjectId);
      const project = projects.find((p) => p.id === queryProjectId);
      if (project) {
        setCurrentProject(project);
      }
    } else if (!selectedProjectId && projects.length > 0) {
      const project = currentProject || projects[0];
      if (!project) return;
      setSelectedProjectId(project.id);
      setCurrentProject(project);
      localStorage.setItem('agent:lastProjectId', project.id);
    }
  }, [projects, currentProject, selectedProjectId, setCurrentProject, queryProjectId]);

  // Load conversations when selected project changes
  // NOTE: Use ref pattern to avoid dependency on loadConversations function
  // which gets recreated on every store update, causing infinite loops
  const loadedProjectIdRef = useRef<string | null>(null);
  const loadConversationsRef = useRef(loadConversations);
  loadConversationsRef.current = loadConversations;

  useEffect(() => {
    if (selectedProjectId && loadedProjectIdRef.current !== selectedProjectId) {
      loadedProjectIdRef.current = selectedProjectId;
      // Use ref to call latest function without triggering effect re-run
      void Promise.resolve(loadConversationsRef.current(selectedProjectId)).catch(
        (error: unknown) => {
          console.error('Failed to load conversations:', error);
        }
      );
    }
    // ONLY depend on selectedProjectId, NOT loadConversations
  }, [selectedProjectId]);

  const loadedSidebarWorkspaceSurfaceRef = useRef<string | null>(null);
  useEffect(() => {
    if (!tenantId || !selectedProjectId || !workspaceIdFromQuery) {
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
    loadWorkspaceSurface,
    selectedProjectId,
    tenantId,
    workspaceIdFromQuery,
    workspaceTasks,
    workspaces,
  ]);

  // Enrich conversations with project info
  const selectedProjectName = useMemo(
    () => projects.find((project) => project.id === selectedProjectId)?.name || 'Unknown Project',
    [projects, selectedProjectId]
  );

  const enrichedConversations: ConversationWithProject[] = useMemo(() => {
    const workspaceNameById = new Map(
      workspaces.map((workspace) => [workspace.id, workspace.name])
    );
    if (currentWorkspace) {
      workspaceNameById.set(currentWorkspace.id, currentWorkspace.name);
    }
    const workspaceTaskTitleById = new Map(workspaceTasks.map((task) => [task.id, task.title]));
    return conversations.map((conv) => ({
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
          conv.workspace_name ?? (workspaceId ? (workspaceNameById.get(workspaceId) ?? null) : null)
        );
      })(),
    }));
  }, [
    conversations,
    currentWorkspace,
    selectedProjectId,
    selectedProjectName,
    workspaceTasks,
    workspaces,
  ]);
  const conversationSections = useMemo(
    () => buildConversationSections(enrichedConversations, t),
    [enrichedConversations, t]
  );
  const [collapsedGroupIds, setCollapsedGroupIds] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    setCollapsedGroupIds((current) => {
      const validGroupIds = new Set(
        conversationSections
          .filter((section) => section.type === 'workspace')
          .map((section) => section.id)
      );
      const next = new Set(Array.from(current).filter((groupId) => validGroupIds.has(groupId)));
      return next.size === current.size ? current : next;
    });
  }, [conversationSections]);

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

  // Preserve sidebar scroll position across re-renders triggered by conversation switch.
  // The conversation list DOM stays the same — only the active highlight changes —
  // so we pin the scroll position to prevent any visual jump.
  const pinnedScrollTopRef = useRef<number | null>(null);
  const prevActiveIdRef = useRef(activeConversationId);

  // Capture scroll position BEFORE React commits DOM changes for the new activeConversationId
  if (prevActiveIdRef.current !== activeConversationId) {
    prevActiveIdRef.current = activeConversationId;
    if (scrollContainerRef.current) {
      pinnedScrollTopRef.current = scrollContainerRef.current.scrollTop;
    }
  }

  // Restore immediately after DOM commit
  useLayoutEffect(() => {
    if (pinnedScrollTopRef.current !== null && scrollContainerRef.current) {
      scrollContainerRef.current.scrollTop = pinnedScrollTopRef.current;
      pinnedScrollTopRef.current = null;
    }
  });

  // Auto-load more conversations when content doesn't fill the container
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container || !hasMoreConversations || isLoadingMoreRef.current || !selectedProjectId) {
      return;
    }

    // Check if content fills the container
    const contentFillsContainer = container.scrollHeight > container.clientHeight + 10;

    // If content doesn't fill container and there are more conversations, load more
    if (!contentFillsContainer && conversations.length > 0) {
      void loadMore().catch((error: unknown) => {
        console.error('Failed to auto-load more conversations:', error);
      });
    }
  }, [conversations.length, hasMoreConversations, selectedProjectId, loadMore]);

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
      Modal.confirm({
        title: t('agent.sidebar.deleteTitle', 'Delete Conversation'),
        content: t('agent.sidebar.deleteConfirm', 'Are you sure? This action cannot be undone.'),
        okText: t('agent.sidebar.delete', 'Delete'),
        cancelText: t('common.cancel', 'Cancel'),
        okType: 'danger',
        onOk: async () => {
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
        },
      });
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
      setSelectedProjectId(projectId);
      localStorage.setItem('agent:lastProjectId', projectId);
      const project = projects.find((p) => p.id === projectId);
      if (project) {
        setCurrentProject(project);
      }
      // NOTE: loadConversations is called by useEffect when selectedProjectId changes
      // Do NOT call it here to avoid duplicate requests
    },
    [projects, setCurrentProject]
  );

  // Get current width for render
  const currentWidth = collapsed ? SIDEBAR_COLLAPSED_WIDTH : sidebarWidth;
  const conversationCountLabel = t('agent.sidebar.conversationCount', {
    count: conversations.length,
    defaultValue: '{{count}} conversations',
  });
  const conversationCountText =
    typeof conversationCountLabel === 'string'
      ? conversationCountLabel
      : `${conversations.length.toString()} ${t('agent.sidebar.conversations', 'conversations')}`;

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
        <div className="p-3 border-b border-slate-100 dark:border-slate-800/50">
          <LazySelect
            value={selectedProjectId}
            onChange={handleProjectChange}
            className="w-full"
            placeholder={t('agent.sidebar.selectProject', 'Select a project')}
            disabled={projects.length === 0}
            suffixIcon={<ChevronDown size={16} />}
            options={projects.map((p) => ({
              value: p.id,
              label: (
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-primary" />
                  <span className="truncate">{p.name}</span>
                </div>
              ),
            }))}
          />
        </div>
      )}

      {/* Collapsed Project Indicator */}
      {collapsed && selectedProjectId && (
        <div className="px-2 pb-2 flex justify-center">
          <Tooltip
            title={
              projects.find((p) => p.id === selectedProjectId)?.name ||
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
                  projects.find((p) => p.id === selectedProjectId)?.name ||
                  t('agent.sidebar.selectProjectTitle', 'Select Project'),
                defaultValue: 'Expand project sidebar for {{project}}',
              })}
              title={t('agent.sidebar.expandProjectSidebar', {
                project:
                  projects.find((p) => p.id === selectedProjectId)?.name ||
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
          disabled={!selectedProjectId}
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
            {isLoadingHistory ? (
              <div className="flex items-center justify-center py-8">
                <div className="w-5 h-5 border-2 border-primary/20 border-t-primary rounded-full animate-spin motion-reduce:animate-none" />
              </div>
            ) : (
              <>
                {enrichedConversations.length === 0 ? (
                  <div className="text-center py-8 text-slate-400">
                    <MessageSquare size={32} className="mx-auto mb-2 opacity-50" />
                    <p className="text-xs">
                      {t('agent.sidebar.noConversations', 'No conversations yet')}
                    </p>
                  </div>
                ) : (
                  conversationSections.map((section) => {
                    if (section.type === 'conversation') {
                      const conv = section.conversation;
                      return (
                        <ConversationItem
                          key={conv.id}
                          conversation={conv}
                          isActive={conv.id === activeConversationId}
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
                                key={conv.id}
                                conversation={conv}
                                grouped
                                isActive={conv.id === activeConversationId}
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
          {contextualNavItems.map((item) => (
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
      )}

      {/* Rename Modal */}
      <Modal
        title={t('agent.sidebar.renameTitle', 'Rename Conversation')}
        open={!!renamingConversation}
        onOk={() => {
          void handleRenameSubmit();
        }}
        onCancel={handleRenameCancel}
        confirmLoading={isRenaming}
        okText={t('agent.sidebar.rename', 'Rename')}
        cancelText={t('common.cancel', 'Cancel')}
      >
        <LazyInput
          placeholder={t('agent.sidebar.renamePlaceholder', 'Enter conversation title')}
          value={newTitle}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
            setNewTitle(e.target.value);
          }}
          onPressEnter={handleRenameSubmit}
          autoFocus
        />
      </Modal>
    </aside>
  );
};

export default TenantChatSidebar;
