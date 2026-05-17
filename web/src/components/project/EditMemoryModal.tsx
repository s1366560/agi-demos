import React, { useState, useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import { X, Loader2, Save } from 'lucide-react';

import { memoryAPI } from '../../services/api';

import type { Memory } from '../../types/memory';

interface EditMemoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  memory: Memory | null;
  onUpdate: () => void;
  projectId: string;
}

export const EditMemoryModal: React.FC<EditMemoryModalProps> = ({
  isOpen,
  onClose,
  memory,
  onUpdate,
  projectId,
}) => {
  const { t } = useTranslation();
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [newTag, setNewTag] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initialize form with memory data
  useEffect(() => {
    if (memory) {
      setTitle(memory.title);
      setContent(memory.content);
      setTags(memory.tags);
    }
  }, [memory]);

  const handleAddTag = () => {
    if (newTag && !tags.includes(newTag)) {
      setTags([...tags, newTag]);
      setNewTag('');
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    setTags(tags.filter((tag) => tag !== tagToRemove));
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();

    if (!memory) return;

    setIsSaving(true);
    setError(null);

    try {
      // Validate version field - required for optimistic locking
      if (typeof memory.version !== 'number') {
        console.error(`Memory ${memory.id} missing or invalid version field`);
        setError('This memory data is outdated. Please refresh the page and try again.');
        setIsSaving(false);
        return;
      }
      const updatedMemory = await memoryAPI.update(projectId, memory.id, {
        title,
        content,
        tags,
        version: memory.version, // Include version for optimistic locking
      });

      if (updatedMemory.task_id) {
        // Graph re-processing started - task_id available for tracking
      }

      // Call the update callback to refresh the list
      onUpdate();
      onClose();
    } catch (err: unknown) {
      console.error('Failed to update memory:', err);
      const error = err as {
        response?:
          | { status?: number | undefined; data?: { detail?: string | undefined } | undefined }
          | undefined;
      };
      // Handle version conflict error specifically
      if (error.response?.status === 409) {
        setError('This memory has been modified by another user. Please refresh and try again.');
      } else {
        setError(error.response?.data?.detail || 'Failed to update memory. Please try again.');
      }
    } finally {
      setIsSaving(false);
    }
  };

  if (!isOpen || !memory) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60">
      <div className="mx-4 flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg bg-white shadow-lg dark:bg-slate-900">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800">
          <div className="flex items-center space-x-2">
            <Save className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
              {t('memory.edit.title')}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            disabled={isSaving}
            aria-label={t('memory.detail.closeAria')}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Form */}
        <form
          onSubmit={(e) => {
            void handleSubmit(e);
          }}
          className="flex-1 overflow-y-auto p-6 space-y-4"
        >
          {error && (
            <div
              className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md p-4"
              role="alert"
              aria-live="assertive"
            >
              <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
            </div>
          )}

          <div>
            <label
              htmlFor="memory-title"
              className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2"
            >
              {t('memory.edit.titleLabel')} *
            </label>
            <input
              id="memory-title"
              type="text"
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
              }}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
              placeholder={t('memory.edit.titlePlaceholder')}
              required
              disabled={isSaving}
              aria-required="true"
            />
          </div>

          <div>
            <label
              htmlFor="memory-content"
              className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2"
            >
              {t('memory.edit.contentLabel')} *
            </label>
            <textarea
              id="memory-content"
              value={content}
              onChange={(e) => {
                setContent(e.target.value);
              }}
              rows={12}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white resize-none"
              placeholder={t('memory.edit.contentPlaceholder')}
              required
              disabled={isSaving}
              aria-required="true"
            />
          </div>

          <div>
            <label
              htmlFor="memory-tags"
              className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2"
            >
              {t('memory.edit.tagsLabel')}
            </label>
            <div className="flex flex-wrap gap-2 mb-2">
              {tags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex items-center gap-1 px-3 py-1 bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300 rounded-full text-sm"
                >
                  {tag}
                  <button
                    type="button"
                    onClick={() => {
                      handleRemoveTag(tag);
                    }}
                    className="hover:text-blue-600 dark:hover:text-blue-400 disabled:opacity-50 rounded-full transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                    disabled={isSaving}
                    aria-label={t('memory.edit.removeTagAria', { tag })}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                id="memory-tags"
                type="text"
                value={newTag}
                onChange={(e) => {
                  setNewTag(e.target.value);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAddTag();
                  }
                }}
                className="flex-1 px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
                placeholder={t('memory.edit.addTagPlaceholder', 'Add new tag')}
                disabled={isSaving}
                aria-label={t('memory.edit.addTagAria', 'Add new tag')}
              />
              <button
                type="button"
                onClick={handleAddTag}
                className="px-4 py-2 bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50"
                disabled={isSaving}
              >
                {t('memory.edit.addTag')}
              </button>
            </div>
          </div>

          {/* Optimistic locking notice */}
          <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-md p-4">
            <p className="text-sm text-yellow-800 dark:text-yellow-300">
              ⚠️ {t('memory.edit.optimisticLockWarning')}
            </p>
          </div>
        </form>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 p-6 border-t border-gray-200 dark:border-slate-800">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50"
            disabled={isSaving}
          >
            {t('memory.edit.cancel')}
          </button>
          <button
            type="button"
            onClick={() => {
              void handleSubmit();
            }}
            className="px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            disabled={isSaving}
          >
            {isSaving && <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />}
            {isSaving ? t('memory.edit.saving') : t('memory.edit.save')}
          </button>
        </div>
      </div>
    </div>
  );
};
