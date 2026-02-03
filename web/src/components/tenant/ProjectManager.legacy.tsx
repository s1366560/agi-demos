import React, { useEffect, useState } from 'react';
import { Folder, Plus, Settings, Trash2, AlertCircle, Search } from 'lucide-react';
import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';
import { Project } from '../../types/memory';
import { ProjectCreateModal } from './ProjectCreateModal';
import { ProjectSettingsModal } from './ProjectSettingsModal';
import { projectService } from '../../services/projectService';

interface ProjectManagerProps {
  onProjectSelect?: (project: Project) => void;
}

export const ProjectManager: React.FC<ProjectManagerProps> = ({ onProjectSelect }) => {
  const { currentTenant } = useTenantStore();
  const { 
    projects, 
    currentProject, 
    listProjects, 
    deleteProject, 
    setCurrentProject, 
    isLoading, 
    error 
  } = useProjectStore();
  
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const [selectedProjectForSettings, setSelectedProjectForSettings] = useState<Project | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterStatus] = useState<string>('all');

  useEffect(() => {
    if (currentTenant) {
      listProjects(currentTenant.id);
    }
  }, [currentTenant, listProjects]);

  const handleProjectSelect = (project: Project) => {
    setCurrentProject(project);
    onProjectSelect?.(project);
  };

  const handleDeleteProject = async (projectId: string) => {
    if (!currentTenant) return;

    if (window.confirm('确定要删除这个项目吗？此操作不可恢复。')) {
      try {
        await deleteProject(currentTenant.id, projectId);
      } catch (_error) {
        // Error is handled in store
      }
    }
  };

  const handleOpenSettings = (project: Project, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedProjectForSettings(project);
    setIsSettingsModalOpen(true);
  };

  const handleSaveSettings = async (projectId: string, updates: Partial<Project>) => {
    try {
      await projectService.updateProject(projectId, {
        name: updates.name || '',
        description: updates.description,
        is_public: updates.is_public || false
      });
      // Refresh project list
      if (currentTenant) {
        await listProjects(currentTenant.id);
      }
      setIsSettingsModalOpen(false);
    } catch (error) {
      console.error('Failed to update project:', error);
      throw error;
    }
  };

  const handleDeleteFromSettings = async (projectId: string) => {
    if (!currentTenant) return;
    try {
      await deleteProject(currentTenant.id, projectId);
      setIsSettingsModalOpen(false);
    } catch (error) {
      console.error('Failed to delete project:', error);
      throw error;
    }
  };

  const filteredProjects = projects.filter(project => {
    const matchesSearch = project.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
                         project.description?.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesFilter = filterStatus === 'all';
    return matchesSearch && matchesFilter;
  });

  if (!currentTenant) {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-8">
        <div className="text-center">
          <Folder className="h-12 w-12 text-gray-400 dark:text-slate-600 mx-auto mb-3" />
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">请先选择工作空间</h3>
          <p className="text-gray-600 dark:text-slate-400">选择一个工作空间来查看和管理项目</p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-8">
        <div className="flex items-center justify-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 dark:border-blue-400"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800">
      <div className="p-6 border-b border-gray-200 dark:border-slate-800">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-2">
            <Folder className="h-5 w-5 text-gray-600 dark:text-slate-400" />
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">项目列表</h3>
          </div>
          <button
            onClick={() => setIsCreateModalOpen(true)}
            className="flex items-center space-x-1 px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors text-sm"
          >
            <Plus className="h-4 w-4" />
            <span>新建项目</span>
          </button>
        </div>

        <div className="flex space-x-4">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400 dark:text-slate-500" />
            <input
              type="text"
              placeholder="搜索项目..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
            />
          </div>
          <div className="relative">
            {/* Filter removed as status is not available */}
          </div>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border-b border-red-200 dark:border-red-900/30">
          <div className="flex items-center space-x-2">
            <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400" />
            <span className="text-sm text-red-800 dark:text-red-300">{error}</span>
          </div>
        </div>
      )}

      <div className="p-6">
        {filteredProjects.length === 0 ? (
          <div className="text-center py-8">
            <Folder className="h-12 w-12 text-gray-400 dark:text-slate-600 mx-auto mb-3" />
            <h4 className="text-lg font-medium text-gray-900 dark:text-white mb-2">暂无项目</h4>
            <p className="text-gray-600 dark:text-slate-400 mb-4">
              {searchTerm || filterStatus !== 'all' 
                ? '没有找到匹配的项目' 
                : '开始创建你的第一个项目'
              }
            </p>
            {!searchTerm && filterStatus === 'all' && (
              <button
                onClick={() => setIsCreateModalOpen(true)}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
              >
                创建项目
              </button>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredProjects.map((project) => (
              <div
                key={project.id}
                className={`p-4 rounded-lg border cursor-pointer transition-all ${
                  currentProject?.id === project.id
                    ? 'border-blue-500 dark:border-blue-400 bg-blue-50 dark:bg-blue-900/20'
                    : 'border-gray-200 dark:border-slate-700 hover:border-gray-300 dark:hover:border-slate-600 hover:bg-gray-50 dark:hover:bg-slate-800'
                }`}
                onClick={() => handleProjectSelect(project)}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center space-x-2">
                    <div className="w-8 h-8 bg-gradient-to-br from-green-500 to-blue-600 rounded-lg flex items-center justify-center">
                      <Folder className="h-4 w-4 text-white" />
                    </div>
                    <div>
                      <h4 className="text-sm font-medium text-gray-900 dark:text-white">{project.name}</h4>
                    </div>
                  </div>
                  <div className="flex items-center space-x-1">
                    <button
                      onClick={(e) => handleOpenSettings(project, e)}
                      className="p-1 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors"
                      title="项目设置"
                    >
                      <Settings className="h-4 w-4" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteProject(project.id);
                      }}
                      className="p-1 text-gray-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 rounded-md transition-colors"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                {project.description && (
                  <p className="text-sm text-gray-600 dark:text-slate-400 mb-3 line-clamp-2">{project.description}</p>
                )}

                <div className="flex items-center justify-between text-xs text-gray-500 dark:text-slate-500">
                  <span>创建于 {new Date(project.created_at).toLocaleDateString()}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <ProjectCreateModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
      />

      {/* Project Settings Modal */}
      {selectedProjectForSettings && (
        <ProjectSettingsModal
          project={selectedProjectForSettings}
          isOpen={isSettingsModalOpen}
          onClose={() => {
            setIsSettingsModalOpen(false);
            setSelectedProjectForSettings(null);
          }}
          onSave={handleSaveSettings}
          onDelete={handleDeleteFromSettings}
        />
      )}

      <ProjectCreateModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        onSuccess={() => {
          if (currentTenant) {
            listProjects(currentTenant.id);
          }
        }}
      />
    </div>
  );
};
