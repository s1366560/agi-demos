/**
 * AgentWorkspace - Tenant-level AI Agent Workspace
 * 
 * Now integrated into TenantLayout which provides the primary navigation sidebar.
 * Project selection is handled by TenantChatSidebar, this component just renders
 * the chat content for the currently selected project.
 */

import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Empty, Spin, Button } from 'antd';
import { useTranslation } from 'react-i18next';
import { useProjectStore } from '../../stores/project';
import { useAgentV3Store } from '../../stores/agentV3';
import { useAuthStore } from '../../stores/auth';
import { useTenantStore } from '../../stores/tenant';
import { AgentChatContent } from '../../components/agent/AgentChatContent';
import type { Project } from '../../types/memory';

/**
 * AgentWorkspace - Main component for tenant-level agent access
 * 
 * Project selection is handled by TenantChatSidebar.
 * This component renders the chat content for the selected project.
 */
export const AgentWorkspace: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { tenantId: urlTenantId } = useParams<{ 
    tenantId?: string;
    conversation?: string;
  }>();
  const { user } = useAuthStore();
  const { currentTenant } = useTenantStore();
  const { projects, currentProject, setCurrentProject, listProjects } = useProjectStore();
  const { loadConversations } = useAgentV3Store();
  
  // Track selected project for this session (synced with TenantChatSidebar via localStorage)
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [initializing, setInitializing] = useState(true);

  // Get effective tenant ID
  const tenantId = urlTenantId || currentTenant?.id || user?.tenant_id;

  // Calculate base path for conversation navigation
  const basePath = tenantId 
    ? `/tenant/${tenantId}/agent-workspace`
    : '/tenant/agent-workspace';

  // Load projects on mount
  useEffect(() => {
    const loadProjects = async () => {
      if (tenantId && projects.length === 0) {
        await listProjects(tenantId);
      }
    };
    loadProjects();
  }, [tenantId, listProjects, projects.length]);

  // Initialize selected project after projects are loaded
  useEffect(() => {
    if (!projects.length) return;

    const init = () => {
      // Try to restore last selected project from localStorage (synced with TenantChatSidebar)
      const lastProjectId = localStorage.getItem('agent:lastProjectId');
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
  }, [projects, currentProject]);

  // Listen for project changes from TenantChatSidebar
  useEffect(() => {
    const handleStorageChange = () => {
      const lastProjectId = localStorage.getItem('agent:lastProjectId');
      if (lastProjectId && lastProjectId !== selectedProjectId) {
        setSelectedProjectId(lastProjectId);
      }
    };

    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, [selectedProjectId]);

  // Load conversations when project changes
  useEffect(() => {
    if (selectedProjectId) {
      loadConversations(selectedProjectId);
      // Update global current project for consistency
      const project = projects.find((p: Project) => p.id === selectedProjectId);
      if (project) {
        setCurrentProject(project);
      }
    }
  }, [selectedProjectId, loadConversations, projects, setCurrentProject]);

  // Show loading while initializing projects
  if (initializing) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <Spin size="large" tip={t('common.loading')} />
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <div className="bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm p-12 max-w-lg">
          <Empty
            description={t('agent.workspace.noProjects')}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            <Button type="primary" onClick={() => navigate('/tenant/projects/new')}>
              {t('tenant.projects.create')}
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
          <Empty description={t('agent.workspace.selectProjectToStart')} />
        </div>
      )}
    </div>
  );
};

export default AgentWorkspace;
