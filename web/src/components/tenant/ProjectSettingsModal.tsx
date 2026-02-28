import React, { useState, useEffect } from 'react';

import { X, Settings, Trash2 } from 'lucide-react';

import { formatDateOnly } from '@/utils/date';

interface Project {
  id: string;
  name: string;
  description?: string | undefined;
  tenant_id: string;
  owner_id: string;
  is_public: boolean;
  created_at: string;
}

interface ProjectSettingsModalProps {
  project: Project;
  isOpen: boolean;
  onClose: () => void;
  onSave: (projectId: string, updates: Partial<Project>) => void;
  onDelete?: ((projectId: string) => void) | undefined;
}

export const ProjectSettingsModal: React.FC<ProjectSettingsModalProps> = ({
  project,
  isOpen,
  onClose,
  onSave,
  onDelete,
}) => {
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description || '');
  const [isPublic, setIsPublic] = useState(project.is_public);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  useEffect(() => {
    setName(project.name);
    setDescription(project.description || '');
    setIsPublic(project.is_public);
  }, [project]);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await onSave(project.id, { name, description, is_public: isPublic });
      onClose();
    } catch (error) {
      console.error('Failed to update project:', error);
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!onDelete) return;

    setIsDeleting(true);
    try {
      await onDelete(project.id);
      onClose();
    } catch (error) {
      console.error('Failed to delete project:', error);
    } finally {
      setIsDeleting(false);
      setShowDeleteConfirm(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white dark:bg-slate-900 rounded-lg shadow-xl w-full max-w-lg mx-4">
        <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800">
          <div className="flex items-center space-x-2">
            <Settings className="h-5 w-5 text-gray-600 dark:text-slate-400" />
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">项目设置</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* Project Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              项目名称 *
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
              }}
              disabled={isSaving}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white disabled:opacity-50 disabled:cursor-not-allowed"
              placeholder="输入项目名称"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              描述
            </label>
            <textarea
              value={description}
              onChange={(e) => {
                setDescription(e.target.value);
              }}
              disabled={isSaving}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500 disabled:opacity-50 disabled:cursor-not-allowed"
              placeholder="添加项目描述..."
            />
          </div>

          {/* Visibility */}
          <div>
            <label className="flex items-center space-x-3">
              <input
                type="checkbox"
                checked={isPublic}
                onChange={(e) => {
                  setIsPublic(e.target.checked);
                }}
                disabled={isSaving}
                className="w-4 h-4 text-blue-600 border-gray-300 dark:border-slate-600 rounded focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
              />
              <span className="text-sm font-medium text-gray-700 dark:text-slate-300">
                公开项目
              </span>
            </label>
            <p className="mt-1 text-xs text-gray-500 dark:text-slate-500">
              公开项目可以被任何拥有链接的人访问
            </p>
          </div>

          {/* Project Info */}
          <div className="pt-4 border-t border-gray-200 dark:border-slate-800">
            <p className="text-xs text-gray-500 dark:text-slate-500">
              项目ID:{' '}
              <code className="px-1 py-0.5 bg-gray-100 dark:bg-slate-800 rounded">
                {project.id}
              </code>
            </p>
            <p className="text-xs text-gray-500 dark:text-slate-500 mt-1">
              创建于 {formatDateOnly(project.created_at)}
            </p>
          </div>

          {/* Delete Section */}
          {onDelete && (
            <div className="pt-4 border-t border-gray-200 dark:border-slate-800">
              {showDeleteConfirm ? (
                <div className="space-y-3">
                  <p className="text-sm text-red-600 dark:text-red-400">
                    确定要删除此项目吗？此操作不可恢复，所有相关的记忆和数据都将被删除。
                  </p>
                  <div className="flex space-x-3">
                    <button
                      type="button"
                      onClick={() => {
                        setShowDeleteConfirm(false);
                      }}
                      disabled={isDeleting}
                      className="flex-1 px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      取消
                    </button>
                    <button
                      type="button"
                      onClick={handleDelete}
                      disabled={isDeleting}
                      className="flex-1 px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isDeleting ? '删除中...' : '确认删除'}
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setShowDeleteConfirm(true);
                  }}
                  className="w-full px-4 py-2 border border-red-300 dark:border-red-900 text-red-600 dark:text-red-400 rounded-md hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors flex items-center justify-center space-x-2"
                >
                  <Trash2 className="h-4 w-4" />
                  <span>删除项目</span>
                </button>
              )}
            </div>
          )}
        </div>

        <div className="flex space-x-3 p-6 border-t border-gray-200 dark:border-slate-800">
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            className="flex-1 px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={isSaving || !name.trim()}
            className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSaving ? '保存中...' : '保存更改'}
          </button>
        </div>
      </div>
    </div>
  );
};
