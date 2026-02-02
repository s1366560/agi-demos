/**
 * AgentWorkspace - Tenant-level AI Agent Workspace
 *
 * Allows users to access Agent Chat from tenant main menu,
 * with project selector for choosing which project's context to use.
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Empty, Spin, Button } from 'antd';
import { useTranslation } from 'react-i18next';
import { useProjectStore } from '../../stores/project';
import { useAgentV3Store } from '../../stores/agentV3';
import { useAuthStore } from '../../stores/auth';
import { useTenantStore } from '../../stores/tenant';
import { AgentChatContent } from '../../components/agent/AgentChatContent';
import { useLocalStorage } from '../../hooks/useLocalStorage';
import type { Project } from '../../types/memory';

/**
 * AgentWorkspace - Main component for tenant-level agent access
 */
export const AgentWorkspace: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { tenantId: urlTenantId } = useParams<{ tenantId?: string }>();

  // Store subscriptions - select only what we need
  const user = useAuthStore((state) => state.user);
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const projects = useProjectStore((state) => state.projects);
  const currentProject = useProjectStore((state) => state.currentProject);
  const setCurrentProject = useProjectStore((state) => state.setCurrentProject);
  const listProjects = useProjectStore((state) => state.listProjects);
  const loadConversations = useAgentV3Store((state) => state.loadConversations);

  // Track selected project for this session - using useLocalStorage for better performance
  const { value: lastProjectId, setValue: setLastProjectId } = useLocalStorage<string | null>(
    'agent:lastProjectId',
    null
  );
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [initializing, setInitializing] = useState(true);

  // Get effective tenant ID - memoized to prevent recalculation
  const tenantId = useMemo(
    () => urlTenantId || currentTenant?.id || user?.tenant_id,
    [urlTenantId, currentTenant?.id, user?.tenant_id]
  );

  // Calculate base path for conversation navigation - memoized
  const basePath = useMemo(
    () => tenantId
      ? `/tenant/${tenantId}/agent-workspace`
      : '/tenant/agent-workspace',
    [tenantId]
  );

  // Navigate to create project - memoized callback
  const handleCreateProject = useCallback(() => {
    navigate('/tenant/projects/new');
  }, [navigate]);

  // Load projects on mount - optimized with removed function dependency
  useEffect(() => {
    const loadProjects = async () => {
      if (tenantId && projects.length === 0) {
        await listProjects(tenantId);
      }
    };
    loadProjects();
  // Only depend on tenantId - listProjects is stable from store
  }, [tenantId]);

  // Initialize selected project after projects are loaded
  useEffect(() => {
    if (!projects.length) return;

    const init = () => {
      // Try to restore last selected project from localStorage (now using cached hook)
      if (lastProjectId && projects.find((p: Project) => p.id === lastProjectId)) {
        setSelectedProjectId(lastProjectId);
      } else if (currentProject) {
        setSelectedProjectId(currentProject.id);
      } else if (projects.length > 0) {
        setSelectedProjectId(projects[0].id);
      }

      setInitializing(false);
    };
    init();
  }, [projects, currentProject, lastProjectId]);

  // Load conversations when project changes
  useEffect(() => {
    if (selectedProjectId) {
      loadConversations(selectedProjectId);
      // Persist selection using cached hook
      setLastProjectId(selectedProjectId);
      // Update global current project for consistency
      const project = projects.find((p: Project) => p.id === selectedProjectId);
      if (project) {
        setCurrentProject(project);
      }
    }
  }, [selectedProjectId, loadConversations, projects, setCurrentProject, setLastProjectId]);

  // Show loading while initializing projects
  if (initializing) {
    return (
      <div className="max-w-full mx-auto w-full h-full flex items-center justify-center">
        <div className="text-center">
          <Spin size="large" />
          <div className="mt-2 text-slate-500 dark:text-slate-400">
            {t('agent.workspace.loading')}
          </div>
        </div>
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="max-w-full mx-auto w-full h-full flex items-center justify-center">
        <div className="bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm p-12 max-w-lg">
          <Empty
            description={t('agent.workspace.noProjects')}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            <Button type="primary" onClick={handleCreateProject}>
              {t('agent.workspace.createProject')}
            </Button>
          </Empty>
        </div>
      </div>
    );
  }

  const effectiveProjectId = selectedProjectId || (projects.length > 0 ? projects[0].id : null);

  return (
    <div className="w-full h-full">
      {effectiveProjectId ? (
        <AgentChatContent
          externalProjectId={effectiveProjectId}
          basePath={basePath}
        />
      ) : (
        <div className="h-full flex items-center justify-center">
          <Empty
            description={t('agent.workspace.selectProjectToStart')}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        </div>
      )}
    </div>
  );
};

export default AgentWorkspace;
