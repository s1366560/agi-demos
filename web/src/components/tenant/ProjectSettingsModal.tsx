import React, { useState, useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import { X, Settings, Trash2 } from 'lucide-react';

import { formatDateOnly } from '@/utils/date';

type AgentConversationMode = 'single_agent' | 'multi_agent_shared' | 'multi_agent_isolated';

interface Project {
  id: string;
  name: string;
  description?: string | undefined;
  tenant_id: string;
  owner_id: string;
  is_public: boolean;
  agent_conversation_mode?: AgentConversationMode;
  created_at: string;
}

interface ProjectSettingsModalProps {
  project: Project;
  isOpen: boolean;
  onClose: () => void;
  onSave: (projectId: string, updates: Partial<Project>) => void | Promise<void>;
  onDelete?: ((projectId: string) => void | Promise<void>) | undefined;
}

export const ProjectSettingsModal: React.FC<ProjectSettingsModalProps> = ({
  project,
  isOpen,
  onClose,
  onSave,
  onDelete,
}) => {
  const { t } = useTranslation();
  const AGENT_MODE_OPTIONS: { value: AgentConversationMode; label: string; hint: string }[] = [
    {
      value: 'single_agent',
      label: t('project.settings.agentMode.singleAgent.label'),
      hint: t('project.settings.agentMode.singleAgent.hint'),
    },
    {
      value: 'multi_agent_shared',
      label: t('project.settings.agentMode.multiShared.label'),
      hint: t('project.settings.agentMode.multiShared.hint'),
    },
    {
      value: 'multi_agent_isolated',
      label: t('project.settings.agentMode.multiIsolated.label'),
      hint: t('project.settings.agentMode.multiIsolated.hint'),
    },
  ];
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description || '');
  const [isPublic, setIsPublic] = useState(project.is_public);
  const [agentMode, setAgentMode] = useState<AgentConversationMode>(
    project.agent_conversation_mode ?? 'single_agent'
  );
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  useEffect(() => {
    setName(project.name);
    setDescription(project.description || '');
    setIsPublic(project.is_public);
    setAgentMode(project.agent_conversation_mode ?? 'single_agent');
  }, [project]);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await onSave(project.id, {
        name,
        description,
        is_public: isPublic,
        agent_conversation_mode: agentMode,
      });
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
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
              {t('project.settings.title')}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* Project Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              {t('project.settings.nameLabel')}
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
              }}
              disabled={isSaving}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white disabled:opacity-50 disabled:cursor-not-allowed"
              placeholder={t('project.settings.namePlaceholder')}
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              {t('project.settings.descriptionLabel')}
            </label>
            <textarea
              value={description}
              onChange={(e) => {
                setDescription(e.target.value);
              }}
              disabled={isSaving}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500 disabled:opacity-50 disabled:cursor-not-allowed"
              placeholder={t('project.settings.descriptionPlaceholder')}
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
                {t('project.settings.publicLabel')}
              </span>
            </label>
            <p className="mt-1 text-xs text-gray-500 dark:text-slate-500">
              {t('project.settings.publicHint')}
            </p>
          </div>

          {/* Agent conversation mode */}
          <div>
            <p className="text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
              {t('project.settings.agentModeLabel')}
            </p>
            <div className="space-y-2">
              {AGENT_MODE_OPTIONS.map((option) => (
                <label
                  key={option.value}
                  className="flex items-start space-x-3 p-2 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 cursor-pointer"
                >
                  <input
                    type="radio"
                    name="agent_conversation_mode"
                    value={option.value}
                    checked={agentMode === option.value}
                    onChange={() => {
                      setAgentMode(option.value);
                    }}
                    disabled={isSaving}
                    className="mt-0.5 w-4 h-4 text-blue-600 border-gray-300 dark:border-slate-600 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                  <span className="flex-1">
                    <span className="block text-sm font-medium text-gray-900 dark:text-slate-100">
                      {option.label}
                    </span>
                    <span className="block text-xs text-gray-500 dark:text-slate-500 mt-0.5">
                      {option.hint}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </div>

          {/* Project Info */}
          <div className="pt-4 border-t border-gray-200 dark:border-slate-800">
            <p className="text-xs text-gray-500 dark:text-slate-500">
              {t('project.settings.projectIdPrefix')}{' '}
              <code className="px-1 py-0.5 bg-gray-100 dark:bg-slate-800 rounded">
                {project.id}
              </code>
            </p>
            <p className="text-xs text-gray-500 dark:text-slate-500 mt-1">
              {t('project.settings.createdAtPrefix')} {formatDateOnly(project.created_at)}
            </p>
          </div>

          {/* Delete Section */}
          {onDelete && (
            <div className="pt-4 border-t border-gray-200 dark:border-slate-800">
              {showDeleteConfirm ? (
                <div className="space-y-3">
                  <p className="text-sm text-red-600 dark:text-red-400">
                    {t('project.settings.deleteConfirmMessage')}
                  </p>
                  <div className="flex space-x-3">
                    <button
                      type="button"
                      onClick={() => {
                        setShowDeleteConfirm(false);
                      }}
                      disabled={isDeleting}
                      className="flex-1 px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {t('project.settings.cancel')}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        void handleDelete();
                      }}
                      disabled={isDeleting}
                      className="flex-1 px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isDeleting
                        ? t('project.settings.deleting')
                        : t('project.settings.confirmDelete')}
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setShowDeleteConfirm(true);
                  }}
                  className="w-full px-4 py-2 border border-red-300 dark:border-red-900 text-red-600 dark:text-red-400 rounded-md hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 flex items-center justify-center space-x-2"
                >
                  <Trash2 className="h-4 w-4" />
                  <span>{t('project.settings.deleteProject')}</span>
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
            className="flex-1 px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {t('project.settings.cancel')}
          </button>
          <button
            type="button"
            onClick={() => {
              void handleSave();
            }}
            disabled={isSaving || !name.trim()}
            className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSaving ? t('project.settings.saving') : t('project.settings.saveChanges')}
          </button>
        </div>
      </div>
    </div>
  );
};
