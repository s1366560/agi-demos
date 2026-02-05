/**
 * ProjectSelector component
 *
 * Allows users to switch between project-scoped agent conversations
 * from within the Agent UI. Implements FR-018.
 *
 * Features:
 * - Dropdown of available projects
 * - Project switching with conversation context preservation
 * - Confirmation when switching with active conversation
 * - Tenant context for projects with duplicate names
 * - Loading and error states
 */

import React, { useState, useMemo } from 'react';

import { ExclamationCircleOutlined, LoadingOutlined } from '@ant-design/icons';

import { Select, Modal, Spin, Alert } from '@/components/ui/lazyAntd';

import { useAgentV3Store } from '../../stores/agentV3';
import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';

const { Option } = Select;

interface ProjectSelectorProps {
  /** Currently selected project ID */
  currentProjectId: string | null;
  /** Callback when project changes */
  onProjectChange: (projectId: string) => void;
  /** Optional CSS class name */
  className?: string;
}

interface ProjectOption {
  id: string;
  name: string;
  tenant_id: string;
  tenant_name?: string;
}

/**
 * ProjectSelector component for switching between project-scoped agent conversations.
 *
 * @example
 * ```tsx
 * <ProjectSelector
 *   currentProjectId={projectId}
 *   onProjectChange={(newId) => navigate(`/project/${newId}/agent`)}
 * />
 * ```
 */
export const ProjectSelector: React.FC<ProjectSelectorProps> = ({
  currentProjectId,
  onProjectChange,
  className,
}) => {
  const { projects, currentProject, isLoading: projectsLoading } = useProjectStore();
  const { 
    activeConversationId, 
    conversations,
    isLoadingHistory,
    error,
    setActiveConversation, 
    loadConversations 
  } = useAgentV3Store();
  const { currentTenant } = useTenantStore();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [pendingProjectId, setPendingProjectId] = useState<string | null>(null);

  // Enrich project options with tenant context for duplicate name handling
  const projectOptions: ProjectOption[] = useMemo(() => {
    return projects.map((project) => ({
      id: project.id,
      name: project.name,
      tenant_id: project.tenant_id,
      // Could add tenant name if needed for distinguishing duplicates
    }));
  }, [projects]);

  // Check if project names are duplicated (need tenant context)
  const hasDuplicateNames = useMemo(() => {
    const names = projectOptions.map((p) => p.name);
    return new Set(names).size !== names.length;
  }, [projectOptions]);

  // Derive current conversation from activeConversationId
  const currentConversation = useMemo(() => {
    return conversations.find(c => c.id === activeConversationId) || null;
  }, [conversations, activeConversationId]);

  // Handle project selection with confirmation for active conversation
  const handleProjectSelect = (projectId: string) => {
    if (projectId === currentProjectId) return;

    // If there's an active conversation, show confirmation
    if (currentConversation && currentConversation.project_id === currentProjectId) {
      setPendingProjectId(projectId);
      setIsModalOpen(true);
    } else {
      executeProjectSwitch(projectId);
    }
  };

  // Execute the project switch after confirmation
  const executeProjectSwitch = async (projectId: string) => {
    try {
      // Clear current conversation state
      setActiveConversation(null);

      // Load conversations for the new project
      await loadConversations(projectId);

      // Trigger the callback
      onProjectChange(projectId);

      setIsModalOpen(false);
      setPendingProjectId(null);
    } catch (error) {
      console.error('Failed to switch projects:', error);
    }
  };

  // Handle modal confirmation
  const handleConfirmSwitch = () => {
    if (pendingProjectId) {
      executeProjectSwitch(pendingProjectId);
    }
  };

  // Handle modal cancellation
  const handleCancelSwitch = () => {
    setIsModalOpen(false);
    setPendingProjectId(null);
  };

  // Loading state indicator
  if (isLoadingHistory) {
    return (
      <div className={className} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
        <Spin indicator={<LoadingOutlined spin />} size="small" />
        <span>Loading conversations...</span>
      </div>
    );
  }

  // Empty project list state
  if (projectOptions.length === 0) {
    return (
      <Select
        placeholder="No projects available"
        disabled
        className={className}
        style={{ width: 250 }}
        aria-label="Select project for agent conversation"
      />
    );
  }

  // Find current project name for display
  const currentProjectName = currentProject?.name || undefined;

  return (
    <>
      <Select
        value={currentProjectId || undefined}
        placeholder="Select a project"
        onChange={handleProjectSelect}
        loading={projectsLoading}
        disabled={projectOptions.length === 1}
        className={className}
        style={{ width: 250 }}
        aria-label="Select project for agent conversation"
        showSearch
        optionFilterProp="children"
        notFoundContent={projectsLoading ? <Spin size="small" /> : 'No projects found'}
      >
        {projectOptions.map((project) => {
          // Display label with tenant context if duplicate names exist
          const label = hasDuplicateNames && currentTenant
            ? `${project.name} (${project.tenant_id === currentTenant.id ? 'Current' : 'Other'} tenant)`
            : project.name;

          return (
            <Option key={project.id} value={project.id} title={label}>
              {label}
            </Option>
          );
        })}
      </Select>

      {/* Confirmation modal for switching with active conversation */}
      <Modal
        title={
          <span>
            <ExclamationCircleOutlined style={{ color: '#faad14', marginRight: 8 }} />
            Switch Project?
          </span>
        }
        open={isModalOpen}
        onOk={handleConfirmSwitch}
        onCancel={handleCancelSwitch}
        okText="Switch Project"
        cancelText="Cancel"
        okButtonProps={{ danger: true }}
      >
        <p>
          You have an active conversation in <strong>{currentProjectName || 'the current project'}</strong>.
          Switching projects will clear this conversation from your view.
        </p>
        <p style={{ color: '#666' }}>
          The conversation will be preserved and can be accessed again by switching back to this project.
        </p>
      </Modal>

      {/* Error display */}
      {error && (
        <Alert
          message="Failed to load conversations"
          description={error}
          type="error"
          closable
          style={{ marginTop: 8 }}
        />
      )}
    </>
  );
};

/**
 * Loading indicator component for async operations
 */
export const ProjectSelectorLoading: React.FC<{ className?: string }> = ({ className }) => (
  <div className={className} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
    <Spin indicator={<LoadingOutlined spin />} size="small" />
    <span data-testid="loading-indicator">Loading...</span>
  </div>
);

/**
 * Empty state component when no projects are available
 */
export const ProjectSelectorEmpty: React.FC<{ className?: string }> = ({ className }) => (
  <Select
    placeholder="No projects available"
    disabled
    className={className}
    style={{ width: 250 }}
    aria-label="Select project for agent conversation"
  />
);
