/**
 * AgentWorkspace - Tenant-level AI Agent Workspace
 * 
 * Allows users to access Agent Chat from tenant main menu,
 * with project selector for choosing which project's context to use.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Select, Empty, Spin, Button } from 'antd';
import { useTranslation } from 'react-i18next';
import { useProjectStore } from '../../stores/project';
import { useAgentV3Store } from '../../stores/agentV3';
import { useAuthStore } from '../../stores/auth';
import { useTenantStore } from '../../stores/tenant';
import { AgentChatContent } from '../../components/agent/AgentChatContent';
import type { Project } from '../../types/memory';

const { Option } = Select;

/**
 * ProjectSelector - Inline project selector for chat header
 */
const ProjectSelector: React.FC<{
  projects: Project[];
  selectedId: string | null;
  onChange: (id: string) => void;
}> = ({ projects, selectedId, onChange }) => {
  const { t } = useTranslation();
  
  return (
    <Select
      value={selectedId}
      onChange={onChange}
      style={{ width: 200 }}
      placeholder={t('agent.workspace.selectProject')}
      showSearch
      optionFilterProp="children"
      filterOption={(input, option) =>
        (option?.children as unknown as string)
          ?.toLowerCase()
          .includes(input.toLowerCase())
      }
      className="agent-project-select"
      bordered={false}
      dropdownMatchSelectWidth={false}
    >
      {projects.map((project: Project) => (
        <Option key={project.id} value={project.id}>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-primary" />
            {project.name}
          </div>
        </Option>
      ))}
    </Select>
  );
};

/**
 * AgentWorkspace - Main component for tenant-level agent access
 */
export const AgentWorkspace: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { tenantId: urlTenantId } = useParams<{ tenantId?: string }>();
  const { user } = useAuthStore();
  const { currentTenant } = useTenantStore();
  const { projects, currentProject, setCurrentProject, listProjects } = useProjectStore();
  const { loadConversations } = useAgentV3Store();
  
  // Track selected project for this session
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
      // Try to restore last selected project from localStorage
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

  // Load conversations when project changes
  useEffect(() => {
    if (selectedProjectId) {
      loadConversations(selectedProjectId);
      // Persist selection
      localStorage.setItem('agent:lastProjectId', selectedProjectId);
      // Update global current project for consistency
      const project = projects.find((p: Project) => p.id === selectedProjectId);
      if (project) {
        setCurrentProject(project);
      }
    }
  }, [selectedProjectId, loadConversations, projects, setCurrentProject]);

  const handleProjectChange = useCallback((projectId: string) => {
    setSelectedProjectId(projectId);
  }, []);

  // Show loading while initializing projects
  if (initializing) {
    return (
      <div className="max-w-full mx-auto w-full h-full flex items-center justify-center">
        <Spin size="large" tip={t('common.loading')} />
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
    <div className="max-w-full mx-auto w-full h-full" style={{ height: 'calc(100vh - 116px)' }}>
      {effectiveProjectId ? (
        <AgentChatContent 
          projectId={effectiveProjectId} 
          key={effectiveProjectId}
          basePath={basePath}
          headerExtra={
            <ProjectSelector
              projects={projects}
              selectedId={selectedProjectId}
              onChange={handleProjectChange}
            />
          }
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
