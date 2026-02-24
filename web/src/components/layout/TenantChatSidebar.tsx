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
import { useNavigate, NavLink } from 'react-router-dom';

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
  LayoutDashboard,
  Folder,
  Headphones,
  Brain,
  ToyBrick,
  BarChart3,
  Settings,
} from 'lucide-react';

import { useAgentV3Store } from '@/stores/agentV3';
import { useProjectStore } from '@/stores/project';

import { formatDistanceToNow } from '@/utils/date';

import {
  LazyButton,
  LazyBadge,
  LazyDropdown,
  LazySelect,
  LazyInput,
} from '@/components/ui/lazyAntd';

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
  onRename?: (e: React.MouseEvent) => void;
  compact?: boolean;
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
          label: 'Rename',
          onClick: () => onRename?.({} as React.MouseEvent),
        },
        {
          key: 'delete',
          icon: <Trash2 size={14} />,
          label: 'Delete',
          danger: true,
          onClick: (e) => { onDelete(e.domEvent as React.MouseEvent); },
        },
      ],
      [onDelete, onRename]
    );

    if (compact) {
      return (
        <Tooltip title={conversation.title || 'Untitled'}>
          <button
            onClick={onSelect}
            className={`
            w-10 h-10 rounded-xl mb-1 transition-all duration-200
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
        onClick={onSelect}
        className={`
        group relative p-3 rounded-xl mb-1 cursor-pointer
        transition-all duration-200 border
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
            <p className="text-xs text-slate-400 mt-0.5">
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
              onClick={(e: React.MouseEvent) => { e.stopPropagation(); }}
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
  tenantId?: string;
  /** Controlled collapsed state */
  collapsed?: boolean;
  /** Callback when collapsed state changes */
  onCollapsedChange?: (collapsed: boolean) => void;
  /** When true, always visible (used inside mobile drawer) */
  mobile?: boolean;
}

export const TenantChatSidebar: React.FC<TenantChatSidebarProps> = ({
  tenantId,
  collapsed: controlledCollapsed,
  onCollapsedChange,
  mobile = false,
}) => {
  const navigate = useNavigate();
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
    conversations,
    activeConversationId,
    isLoadingHistory,
    loadConversations,
    loadMoreConversations,
    createNewConversation,
    deleteConversation,
    hasMoreConversations,
  } = useAgentV3Store();

  const { projects, currentProject, listProjects, setCurrentProject } = useProjectStore();

  // Sync ref with state when not dragging
  useEffect(() => {
    if (!isDragging) {
      widthRef.current = sidebarWidth;
    }
  }, [sidebarWidth, isDragging]);

  // Load projects on mount
  useEffect(() => {
    if (tenantId && projects.length === 0) {
      listProjects(tenantId);
    }
  }, [tenantId, projects.length, listProjects]);

  // Set default selected project
  useEffect(() => {
    if (!selectedProjectId && projects.length > 0) {
      const project = currentProject || projects[0];
      if (!project) return;
      setSelectedProjectId(project.id);
      setCurrentProject(project);
      localStorage.setItem('agent:lastProjectId', project.id);
    }
  }, [projects, currentProject, selectedProjectId, setCurrentProject]);

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
      loadConversationsRef.current(selectedProjectId);
    }
    // ONLY depend on selectedProjectId, NOT loadConversations
  }, [selectedProjectId]);

  // Enrich conversations with project info
  const enrichedConversations: ConversationWithProject[] = useMemo(() => {
    return conversations.map((conv) => ({
      ...conv,
      projectId: selectedProjectId || '',
      projectName: projects.find((p) => p.id === selectedProjectId)?.name || 'Unknown Project',
    }));
  }, [conversations, selectedProjectId, projects]);

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
        loadMore();
      }
    },
    [hasMoreConversations, selectedProjectId, loadMore]
  );

  const handleSelectConversation = useCallback(
    (id: string, projectId: string) => {
      if (tenantId) {
        navigate(`/tenant/${tenantId}/agent-workspace/${id}?projectId=${projectId}`);
      } else {
        navigate(`/tenant/agent-workspace/${id}?projectId=${projectId}`);
      }
    },
    [navigate, tenantId]
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
      loadMore();
    }
  }, [conversations.length, hasMoreConversations, selectedProjectId, loadMore]);

  const handleNewConversation = useCallback(async () => {
    if (!selectedProjectId) return;
    const newId = await createNewConversation(selectedProjectId);
    if (newId) {
      if (tenantId) {
        navigate(`/tenant/${tenantId}/agent-workspace/${newId}?projectId=${selectedProjectId}`);
      } else {
        navigate(`/tenant/agent-workspace/${newId}?projectId=${selectedProjectId}`);
      }
    }
  }, [selectedProjectId, createNewConversation, navigate, tenantId]);

  const handleDeleteConversation = useCallback(
    (id: string, e: React.MouseEvent) => {
      e.stopPropagation();
      if (!selectedProjectId) return;
      Modal.confirm({
        title: 'Delete Conversation',
        content: 'Are you sure? This action cannot be undone.',
        okText: 'Delete',
        okType: 'danger',
        onOk: async () => {
          await deleteConversation(id, selectedProjectId);
          if (activeConversationId === id) {
            if (tenantId) {
              navigate(`/tenant/${tenantId}/agent-workspace`);
            } else {
              navigate(`/tenant/agent-workspace`);
            }
          }
        },
      });
    },
    [selectedProjectId, activeConversationId, deleteConversation, navigate, tenantId]
  );

  // Rename conversation state and handlers
  const [renamingConversation, setRenamingConversation] = useState<ConversationWithProject | null>(
    null
  );
  const [newTitle, setNewTitle] = useState('');
  const [isRenaming, setIsRenaming] = useState(false);
  const { renameConversation } = useAgentV3Store();

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

  // Optimized drag handlers using RAF
  const handleResizeStart = useCallback(
    (e: React.MouseEvent) => {
      if (collapsed) return; // Don't resize when collapsed

      e.preventDefault();
      e.stopPropagation();
      setIsDragging(true);

      const startX = e.clientX;
      const startWidth = widthRef.current;
      let rafId: number | null = null;
      let currentWidth = startWidth;

      const handleMouseMove = (e: MouseEvent) => {
        if (rafId) return;

        rafId = requestAnimationFrame(() => {
          rafId = null;
          const delta = e.clientX - startX;
          currentWidth = Math.max(
            SIDEBAR_MIN_WIDTH,
            Math.min(SIDEBAR_MAX_WIDTH, startWidth + delta)
          );

          if (sidebarRef.current) {
            sidebarRef.current.style.width = `${currentWidth}px`;
          }
        });
      };

      const handleMouseUp = () => {
        if (rafId) {
          cancelAnimationFrame(rafId);
        }

        if (currentWidth < COLLAPSE_THRESHOLD) {
          setCollapsed(true);
          setSidebarWidth(SIDEBAR_DEFAULT_WIDTH);
          widthRef.current = SIDEBAR_DEFAULT_WIDTH;
          if (sidebarRef.current) {
            sidebarRef.current.style.width = `${SIDEBAR_COLLAPSED_WIDTH}px`;
          }
        } else {
          setCollapsed(false);
          setSidebarWidth(currentWidth);
          widthRef.current = currentWidth;
        }

        setIsDragging(false);
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
      };

      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'ew-resize';
    },
    [collapsed, setCollapsed]
  );

  // Get current width for render
  const currentWidth = collapsed ? SIDEBAR_COLLAPSED_WIDTH : sidebarWidth;

  return (
    <aside
      ref={sidebarRef}
      className={`
        ${mobile ? 'flex' : 'hidden md:flex'}
        flex-col bg-surface-light dark:bg-surface-dark border-r border-slate-200 dark:border-border-dark 
        flex-none z-20 h-full relative
        ${isDragging ? '' : 'transition-all duration-300 ease-in-out'}
      `}
      style={{ width: mobile ? '100%' : currentWidth }}
    >
      {/* Resize Handle - only show when not collapsed */}
      {!collapsed && (
        <div
          onMouseDown={handleResizeStart}
          className={`
            absolute right-0 top-0 bottom-0 w-2 cursor-ew-resize z-50
            flex items-center justify-center
            bg-transparent
            hover:bg-slate-200/50 dark:hover:bg-slate-700/50
            ${isDragging ? 'bg-slate-300/70 dark:bg-slate-600/70' : ''}
            transition-all duration-150
            group/handle
          `}
        >
          <div
            className={`
            w-0.5 h-6 rounded-full
            bg-slate-400/50 dark:bg-slate-500/50
            opacity-0 group-hover/handle:opacity-100
            ${isDragging ? 'opacity-100 bg-slate-500 dark:bg-slate-400' : ''}
            transition-all duration-150
          `}
          />
        </div>
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
                Agent Workspace
              </h2>
              <p className="text-xs text-slate-500">{conversations.length} conversations</p>
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
            placeholder="Select a project"
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
            title={projects.find((p) => p.id === selectedProjectId)?.name || 'Select Project'}
          >
            <button
              onClick={() => { setCollapsed(false); }}
              className="w-10 h-10 rounded-xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
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
          {!collapsed && <span>New Chat</span>}
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
              <div className="w-5 h-5 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
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
                  <p className="text-xs">No conversations yet</p>
                </div>
              ) : (
                enrichedConversations.map((conv) => (
                  <ConversationItem
                    key={conv.id}
                    conversation={conv}
                    isActive={conv.id === activeConversationId}
                    onSelect={() => { handleSelectConversation(conv.id, conv.projectId); }}
                    onDelete={(e) => { handleDeleteConversation(conv.id, e); }}
                    onRename={(e) => { handleRenameClick(conv, e); }}
                    compact={collapsed}
                  />
                ))
              )}
              {isLoadingMore && !collapsed && (
                <div className="flex items-center justify-center py-3">
                  <div className="w-4 h-4 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Mobile Navigation Links - shown only in mobile drawer */}
      {mobile && tenantId && (
        <div className="border-t border-slate-100 dark:border-slate-800/50 px-3 py-2">
          <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider px-2 mb-1">
            {t('nav.navigation', 'Navigation')}
          </p>
          {[
            {
              path: `/tenant/${tenantId}/overview`,
              icon: <LayoutDashboard size={16} />,
              label: t('nav.overview', 'Overview'),
            },
            {
              path: `/tenant/${tenantId}/projects`,
              icon: <Folder size={16} />,
              label: t('nav.projects', 'Projects'),
            },
            {
              path: `/tenant/${tenantId}/agents`,
              icon: <Headphones size={16} />,
              label: t('nav.agents', 'Agents'),
            },
            {
              path: `/tenant/${tenantId}/skills`,
              icon: <Brain size={16} />,
              label: t('nav.skills', 'Skills'),
            },
            {
              path: `/tenant/${tenantId}/plugins`,
              icon: <ToyBrick size={16} />,
              label: t('nav.plugins', 'Plugins'),
            },
            {
              path: `/tenant/${tenantId}/analytics`,
              icon: <BarChart3 size={16} />,
              label: t('nav.analytics', 'Analytics'),
            },
            {
              path: `/tenant/${tenantId}/settings`,
              icon: <Settings size={16} />,
              label: t('nav.settings', 'Settings'),
            },
          ].map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-2 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-primary/10 text-primary font-medium'
                    : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
                }`
              }
            >
              {item.icon}
              <span>{item.label}</span>
            </NavLink>
          ))}
        </div>
      )}

      {/* Footer - AI Status */}
      {!collapsed && (
        <div className="p-3 border-t border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-3 p-2 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-700">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-primary-light flex items-center justify-center shadow-sm">
              <Bot size={16} className="text-white" />
            </div>
            <div className="flex flex-col overflow-hidden min-w-0 flex-1">
              <p className="text-sm font-medium text-slate-900 dark:text-white truncate leading-5">
                AI Assistant
              </p>
              <div className="flex items-center gap-1.5">
                <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />
                <p className="text-xs text-emerald-500 dark:text-emerald-400 truncate leading-4">
                  Online
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Rename Modal */}
      <Modal
        title="Rename Conversation"
        open={!!renamingConversation}
        onOk={handleRenameSubmit}
        onCancel={handleRenameCancel}
        confirmLoading={isRenaming}
        okText="Rename"
        cancelText="Cancel"
      >
        <LazyInput
          placeholder="Enter conversation title"
          value={newTitle}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => { setNewTitle(e.target.value); }}
          onPressEnter={handleRenameSubmit}
          autoFocus
        />
      </Modal>
    </aside>
  );
};

export default TenantChatSidebar;
