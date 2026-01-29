/**
 * AgentWorkspace - Tenant-level AI Agent Workspace
 * 
 * Allows users to access Agent Chat from tenant main menu,
 * with project selector for choosing which project's context to use.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Select, Empty, Spin } from 'antd';
import { useProjectStore } from '../../stores/project';
import { useAgentV3Store } from '../../stores/agentV3';
import { AgentChatContent } from '../../components/agent/AgentChatContent';
import type { Project } from '../../types/project';

const { Option } = Select;

/**
 * AgentWorkspace - Main component for tenant-level agent access
 * 
 * Features:
 * - Project selector for choosing context
 * - Persist last selected project in localStorage
 * - Show all conversations across projects (optional enhancement)
 * - Or show conversations for selected project only
 */
export const AgentWorkspace: React.FC = () => {
  const navigate = useNavigate();
  const { tenantId } = useParams<{ tenantId: string }>();
  const { projects, currentProject, setCurrentProject, fetchProjects } = useProjectStore();
  const { conversations, loadConversations } = useAgentV3Store();
  
  // Track selected project for this session
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Load projects on mount
  useEffect(() => {
    const init = async () => {
      if (projects.length === 0) {
        await fetchProjects();
      }
      
      // Try to restore last selected project from localStorage
      const lastProjectId = localStorage.getItem('agent:lastProjectId');
      if (lastProjectId && projects.find(p => p.id === lastProjectId)) {
        setSelectedProjectId(lastProjectId);
      } else if (currentProject) {
        setSelectedProjectId(currentProject.id);
      } else if (projects.length > 0) {
        setSelectedProjectId(projects[0].id);
      }
      
      setLoading(false);
    };
    init();
  }, [projects.length, currentProject, fetchProjects]);

  // Load conversations when project changes
  useEffect(() => {
    if (selectedProjectId) {
      loadConversations(selectedProjectId);
      // Persist selection
      localStorage.setItem('agent:lastProjectId', selectedProjectId);
      // Update global current project for consistency
      const project = projects.find(p => p.id === selectedProjectId);
      if (project) {
        setCurrentProject(project);
      }
    }
  }, [selectedProjectId, loadConversations, projects, setCurrentProject]);

  const handleProjectChange = useCallback((projectId: string) => {
    setSelectedProjectId(projectId);
  }, []);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Spin size="large" tip="Loading..." />
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <Empty
          description="No projects available"
          buttonProps={{
            children: 'Create Project',
            onClick: () => navigate('/projects/new'),
          }}
        />
      </div>
    );
  }

  const selectedProject = projects.find(p => p.id === selectedProjectId);

  return (
    <div className="h-full flex flex-col bg-slate-50 dark:bg-slate-900">
      {/* Header with Project Selector */}
      <div className="bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-semibold text-slate-900 dark:text-white">
            AI Agent Workspace
          </h1>
          
          {/* Project Selector */}
          <Select
            value={selectedProjectId}
            onChange={handleProjectChange}
            style={{ width: 240 }}
            placeholder="Select a project"
            showSearch
            optionFilterProp="children"
            filterOption={(input, option) =>
              (option?.children as unknown as string)
                ?.toLowerCase()
                .includes(input.toLowerCase())
            }
          >
            {projects.map(project => (
              <Option key={project.id} value={project.id}>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full" 
                    style={{ backgroundColor: project.color || '#1890ff' }} 
                  />
                  {project.name}
                </div>
              </Option>
            ))}
          </Select>
        </div>

        {/* Quick Actions */}
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">
            {selectedProject && `Context: ${selectedProject.name}`}
          </span>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-hidden">
        {selectedProjectId ? (
          <AgentChatContent 
            projectId={selectedProjectId} 
            key={selectedProjectId} // Force re-mount on project change
          />
        ) : (
          <div className="h-full flex items-center justify-center">
            <Empty description="Please select a project to start" />
          </div>
        )}
      </div>
    </div>
  );
};

export default AgentWorkspace;
