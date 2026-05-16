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
} from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useConversationsStore } from '@/stores/agent/conversationsStore';
import { useIsLoadingHistory } from '@/stores/agent/timelineStore';
import { useAgentV3Store } from '@/stores/agentV3';
import { useProjectStore } from '@/stores/project';
import { useCurrentWorkspace, useWorkspaces } from '@/stores/workspace';

import { buildAgentWorkspacePath } from '@/utils/agentWorkspacePath';
import { formatDistanceToNow } from '@/utils/date';

import {
  getContextualTopNavItems,
  isContextualTopNavItemActive,
} from '@/components/layout/TenantHeader';
import {
  LazyButton,
  LazyBadge,
  LazyDropdown,
  LazySelect,
  LazyInput,
} from '@/components/ui/lazyAntd';

import { Resizer } from '../agent/Resizer';

import type { Conversation } from '@/types/agent';

import type { MenuProps } from 'antd';

interface ConversationWithProject extends Conversation {
  projectId: string;
  projectName: string;
}

interface ConversationItemProps {
  conversation: ConversationWithProject;
  isActive: boolean;
  onSelect: () => void;
  onDelete: (e: React.MouseEvent) => void;
  onRename?: ((e: React.MouseEvent) => void) | undefined;
  compact?: boolean | undefined;
}

// Constants for resize constraints
const SIDEBAR_MIN_WIDTH = 200;
const SIDEBAR_MAX_WIDTH = 400;
const SIDEBAR_DEFAULT_WIDTH = 256;
const SIDEBAR_COLLAPSED_WIDTH = 80;
const COLLAPSE_THRESHOLD = 120; // Width below which sidebar collapses

// Memoized ConversationItem to prevent unnecessary re-renders (rerender-memo)
const ConversationItem: React.FC<ConversationItemProps> = memo(
  ({ conversation, isActive, onSelect, onDelete, onRename, compact = false }) => {
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

    if (compact) {
      return (
        <Tooltip title={conversation.title || t('agent.sidebar.untitled', 'Untitled')}>
          <button
            type="button"
            onClick={onSelect}
            className={`
            w-10 h-10 rounded-xl mb-1 transition-[color,background-color,border-color,box-shadow,opacity,transform,width] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1
            flex items-center justify-center relative mx-auto
            ${
              isActive
                ? 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200'
                : 'text-slate-500 hover:bg-slate-50 dark:hover:bg-slate-800/60'
            }
          `}
          >
            <MessageSquare size={20} />
            {isActive && (
              <span className="absolute left-0 w-0.5 h-5 bg-slate-400 dark:bg-slate-500 rounded-r-full" />
            )}
          </button>
        </Tooltip>
      );
    }

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
        <div className="flex items-start gap-3">
          {/* Icon */}
          <div
            className={`
          w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0
          ${
            isActive
              ? 'bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300'
              : 'bg-slate-100 dark:bg-slate-800 text-slate-500'
          }
        `}
          >
            <MessageSquare size={18} />
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium text-sm truncate">
                {conversation.title || 'Untitled Conversation'}
              </p>
              {conversation.status === 'active' && (
                <LazyBadge status="processing" className="flex-shrink-0" />
              )}
            </div>
            <p className="text-xs text-slate-400 mt-0.5 truncate">
              {conversation.projectName} · {timeAgo}
            </p>
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
  const workspaces = useWorkspaces();

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

  // Enrich conversations with project info
  const selectedProjectName = useMemo(
    () => projects.find((project) => project.id === selectedProjectId)?.name || 'Unknown Project',
    [projects, selectedProjectId]
  );

  const enrichedConversations: ConversationWithProject[] = useMemo(() => {
    return conversations.map((conv) => ({
      ...conv,
      projectId: selectedProjectId || '',
      projectName: selectedProjectName,
    }));
  }, [conversations, selectedProjectId, selectedProjectName]);

  const isLoadingMoreRef = useRef(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const workspaceIdFromQuery = useMemo(() => {
    if (!location.search) return null;
    return new URLSearchParams(location.search).get('workspaceId');
  }, [location.search]);

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
          workspaceId: workspaceIdFromQuery,
        })
      );
    }
  }, [selectedProjectId, createNewConversation, navigate, tenantId, workspaceIdFromQuery]);

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
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-primary-light flex items-center justify-center shadow-sm shrink-0">
              <Bot className="text-white" size={24} />
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="font-semibold text-slate-900 dark:text-slate-100 truncate text-sm">
                {t('agent.sidebar.workspaceTitle', 'Agent Workspace')}
              </h2>
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
        <div className={collapsed ? 'px-2' : 'px-3'}>
          {isLoadingHistory ? (
            <div className="flex items-center justify-center py-8">
              <div className="w-5 h-5 border-2 border-primary/20 border-t-primary rounded-full animate-spin motion-reduce:animate-none" />
            </div>
          ) : (
            <>
              {enrichedConversations.length === 0 ? (
                <div
                  className={`
                  text-center py-8 text-slate-400
                  ${collapsed ? 'hidden' : 'block'}
                `}
                >
                  <MessageSquare size={32} className="mx-auto mb-2 opacity-50" />
                  <p className="text-xs">
                    {t('agent.sidebar.noConversations', 'No conversations yet')}
                  </p>
                </div>
              ) : (
                enrichedConversations.map((conv) => (
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
                    compact={collapsed}
                  />
                ))
              )}
              {isLoadingMore && !collapsed && (
                <div className="flex items-center justify-center py-3">
                  <div className="w-4 h-4 border-2 border-primary/20 border-t-primary rounded-full animate-spin motion-reduce:animate-none" />
                </div>
              )}
            </>
          )}
        </div>
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
