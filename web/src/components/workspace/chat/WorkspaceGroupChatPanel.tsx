import React, { useEffect, useMemo, useCallback, useState, useRef } from 'react';

import { useTranslation } from 'react-i18next';

import { Users, MessageSquare, ChevronDown, Check, Hash } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useWorkspaceStore } from '@/stores/workspace';

import { ChatPanel } from './ChatPanel';

export interface WorkspaceGroupChatPanelProps {
  tenantId: string;
  projectId: string;
  workspaceId: string | null;
  onWorkspaceChange?: (workspaceId: string) => void;
}

export const WorkspaceGroupChatPanel: React.FC<WorkspaceGroupChatPanelProps> = ({
  tenantId,
  projectId,
  workspaceId,
  onWorkspaceChange,
}) => {
  const { t } = useTranslation();
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);

  const { members, agents, currentWorkspace, workspaces, loadWorkspaceSurface, loadWorkspaces } =
    useWorkspaceStore(
      useShallow((state) => ({
        members: state.members,
        agents: state.agents,
        currentWorkspace: state.currentWorkspace,
        workspaces: state.workspaces,
        loadWorkspaceSurface: state.loadWorkspaceSurface,
        loadWorkspaces: state.loadWorkspaces,
      })),
    );

  // Load workspace list if empty
  useEffect(() => {
    if (tenantId && projectId && workspaces.length === 0) {
      void loadWorkspaces(tenantId, projectId);
    }
  }, [tenantId, projectId, workspaces.length, loadWorkspaces]);

  // Load workspace surface data if not already loaded for this workspace
  useEffect(() => {
    if (workspaceId && tenantId && projectId && currentWorkspace?.id !== workspaceId) {
      void loadWorkspaceSurface(tenantId, projectId, workspaceId);
    }
  }, [workspaceId, tenantId, projectId, currentWorkspace?.id, loadWorkspaceSurface]);

  // Close picker on click outside
  useEffect(() => {
    if (!pickerOpen) return;
    const handler = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setPickerOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [pickerOpen]);

  const handleSelect = useCallback(
    (id: string) => {
      setPickerOpen(false);
      if (id === workspaceId) return;
      // Persist to localStorage
      try {
        localStorage.setItem('agent:lastWorkspaceId', JSON.stringify(id));
      } catch {
        // ignore
      }
      // Notify parent or load directly
      if (onWorkspaceChange) {
        onWorkspaceChange(id);
      }
      if (tenantId && projectId) {
        void loadWorkspaceSurface(tenantId, projectId, id);
      }
    },
    [workspaceId, tenantId, projectId, onWorkspaceChange, loadWorkspaceSurface],
  );

  const currentName = useMemo(
    () => workspaces.find((w) => w.id === workspaceId)?.name ?? 'Workspace Chat',
    [workspaces, workspaceId],
  );

  if (!workspaceId) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-slate-50 p-8 dark:bg-slate-900">
        <MessageSquare className="h-10 w-10 text-slate-300 dark:text-slate-600" />
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {t('agent.collab.noWorkspace', 'No workspace selected')}
        </p>
      </div>
    );
  }

  const participantCount = members.length + agents.length;

  return (
    <div className="flex h-full flex-col overflow-hidden bg-white dark:bg-slate-900">
      <div className="flex shrink-0 items-center gap-2.5 border-b border-slate-200/60 bg-slate-50 px-4 py-2.5 dark:border-slate-700/50 dark:bg-slate-800/80">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-100 dark:bg-indigo-900/50">
          <Users className="h-3.5 w-3.5 text-indigo-600 dark:text-indigo-400" />
        </div>
        <div className="relative min-w-0 flex-1" ref={pickerRef}>
          {workspaces.length > 1 ? (
            <>
              <button
                type="button"
                onClick={() => setPickerOpen((p) => !p)}
                className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-0.5 text-left transition-colors hover:bg-slate-100 dark:hover:bg-slate-700/50"
              >
                <span className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {currentName}
                </span>
                <ChevronDown className={`h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform ${pickerOpen ? 'rotate-180' : ''}`} />
              </button>
              {pickerOpen && (
                <div className="absolute left-0 top-full z-50 mt-1.5 w-64 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-800">
                  <div className="px-3 py-2 text-xs font-medium uppercase tracking-wider text-slate-400">
                    Workspaces
                  </div>
                  <div className="max-h-56 overflow-y-auto">
                    {workspaces.map((w) => {
                      const isActive = w.id === workspaceId;
                      return (
                        <button
                          key={w.id}
                          type="button"
                          onClick={() => handleSelect(w.id)}
                          className={`flex w-full items-center gap-2.5 border-0 px-3 py-2 text-left transition-colors ${
                            isActive
                              ? 'bg-indigo-50 dark:bg-indigo-900/30'
                              : 'bg-transparent hover:bg-slate-50 dark:hover:bg-slate-700/40'
                          }`}
                        >
                          <Hash className={`h-3.5 w-3.5 shrink-0 ${isActive ? 'text-indigo-500' : 'text-slate-400'}`} />
                          <div className="min-w-0 flex-1">
                            <span className={`block truncate text-sm ${isActive ? 'font-semibold text-indigo-700 dark:text-indigo-300' : 'font-medium text-slate-700 dark:text-slate-300'}`}>
                              {w.name}
                            </span>
                            {w.description && (
                              <span className="block truncate text-xs text-slate-400 dark:text-slate-500">
                                {w.description}
                              </span>
                            )}
                          </div>
                          {isActive && (
                            <Check className="h-3.5 w-3.5 shrink-0 text-indigo-500" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          ) : (
            <h3 className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
              {currentName}
            </h3>
          )}
        </div>
        {participantCount > 0 && (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-700 dark:text-slate-400">
            {participantCount}
          </span>
        )}
      </div>
      <div className="flex-1 overflow-hidden">
        <ChatPanel tenantId={tenantId} projectId={projectId} workspaceId={workspaceId} />
      </div>
    </div>
  );
};
