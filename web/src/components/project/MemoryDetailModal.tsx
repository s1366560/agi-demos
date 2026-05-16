import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { message } from 'antd';
import {
  X,
  Brain,
  User,
  Calendar,
  Tag,
  Hash,
  Eye,
  Edit3,
  Share2,
  Download,
  Save,
  XCircle,
} from 'lucide-react';

import { formatDateTimeFull } from '@/utils/date';

import { memoryService } from '../../services/memoryService';

import type { Memory } from '../../types/memory';

interface MemoryDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  memory: Memory | null;
  shareUrl?: string | undefined;
  onUpdated?: ((memory: Memory) => void) | undefined;
}

const getErrorMessage = (error: unknown): string => {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  if (typeof error === 'object' && error !== null && 'message' in error) {
    const message = (error as { message?: unknown }).message;
    return typeof message === 'string' ? message : '';
  }
  return '';
};

const formatMetadataValue = (value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value);
  }
  if (typeof value === 'symbol') return value.toString();
  if (typeof value === 'function') return '[Function]';
  if (typeof value === 'object') return JSON.stringify(value);
  return '';
};

const getViewCount = (metadata: Record<string, unknown>): number => {
  const value = metadata.view_count;
  if (typeof value === 'number') return value;
  if (typeof value !== 'string') return 0;

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export const MemoryDetailModal: React.FC<MemoryDetailModalProps> = ({
  isOpen,
  onClose,
  memory: memoryProp,
  shareUrl,
  onUpdated,
}) => {
  const { t } = useTranslation();
  const [isEditing, setIsEditing] = useState(false);
  const [displayMemory, setDisplayMemory] = useState<Memory | null>(memoryProp);
  const [editedContent, setEditedContent] = useState(memoryProp?.content || '');
  const [editedTitle, setEditedTitle] = useState(memoryProp?.title || '');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDisplayMemory(memoryProp);
    setEditedContent(memoryProp?.content || '');
    setEditedTitle(memoryProp?.title || '');
    setIsEditing(false);
    setError(null);
  }, [memoryProp]);

  const memory =
    memoryProp && displayMemory?.id === memoryProp.id ? displayMemory : memoryProp;

  if (!isOpen || !memory) return null;

  const formatDate = (dateString: string) => {
    if (!dateString) return '';
    return formatDateTimeFull(dateString);
  };

  const getTypeColor = (type: string) => {
    switch (type) {
      case 'text':
        return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300';
      case 'document':
        return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300';
      case 'image':
        return 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300';
      case 'video':
        return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300';
      default:
        return 'bg-gray-100 text-gray-800 dark:bg-slate-800 dark:text-slate-200';
    }
  };

  const handleEdit = () => {
    // Enter edit mode
    setEditedTitle(memory.title);
    setEditedContent(memory.content);
    setIsEditing(true);
    setError(null);
  };

  const handleSave = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const updatedMemory = await memoryService.updateMemory(memory.id, {
        title: editedTitle,
        content: editedContent,
        version: memory.version,
      });

      setDisplayMemory(updatedMemory);
      setEditedTitle(updatedMemory.title);
      setEditedContent(updatedMemory.content);
      setIsEditing(false);
      onUpdated?.(updatedMemory);
    } catch (err: unknown) {
      console.error('Failed to update memory:', err);
      const errorMessage = getErrorMessage(err);
      if (errorMessage.includes('409')) {
        setError(t('memory.detail.versionConflict'));
      } else {
        setError(t('memory.detail.saveFailed'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleCancel = () => {
    // Exit edit mode without saving
    setIsEditing(false);
    setEditedTitle(memory.title);
    setEditedContent(memory.content);
    setError(null);
  };

  const handleShare = async () => {
    const memoryShareUrl = shareUrl ?? window.location.href;

    try {
      await navigator.clipboard.writeText(memoryShareUrl);
      void message.success(t('memory.detail.linkCopied'));
    } catch (err) {
      console.error('Failed to copy link:', err);
      void message.error(t('memory.detail.linkCopyFailed'));
    }
  };

  const handleDownload = () => {
    const data = JSON.stringify(memory, null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `memory-${memory.id}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const hasEntities = memory.entities.length > 0;
  const hasRelationships = memory.relationships.length > 0;
  const hasMetadata = Object.keys(memory.metadata).length > 0;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 backdrop-blur-sm flex items-center justify-center z-50">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="memory-detail-title"
        className="bg-white dark:bg-slate-900 rounded-lg shadow-xl w-full max-w-4xl mx-4 max-h-[90vh] overflow-hidden"
      >
        <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800">
          <div className="flex items-center space-x-2">
            <Brain className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            <h2
              id="memory-detail-title"
              className="text-lg font-semibold text-gray-900 dark:text-white"
            >
              {isEditing ? t('memory.detail.editTitle') : t('memory.detail.title')}
            </h2>
          </div>
          <div className="flex items-center space-x-2">
            {isEditing ? (
              <>
                <button
                  onClick={() => {
                    void handleSave();
                  }}
                  disabled={isLoading}
                  className="p-2 text-green-600 dark:text-green-400 hover:bg-green-50 dark:hover:bg-green-900/20 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:opacity-50"
                  aria-label={t('memory.detail.saveAria')}
                  title={t('memory.detail.saveTitle')}
                >
                  {isLoading ? (
                    <div className="animate-spin motion-reduce:animate-none rounded-full h-4 w-4 border-b-2 border-green-600"></div>
                  ) : (
                    <Save className="h-4 w-4" />
                  )}
                </button>
                <button
                  onClick={handleCancel}
                  disabled={isLoading}
                  className="p-2 text-gray-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:opacity-50"
                  aria-label={t('memory.detail.cancelAria')}
                  title={t('memory.detail.cancelTitle')}
                >
                  <XCircle className="h-4 w-4" />
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={handleEdit}
                  className="p-2 text-gray-400 dark:text-slate-500 hover:text-blue-600 dark:hover:text-blue-400 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                  aria-label={t('memory.detail.editAria')}
                  title={t('memory.detail.editTitleTooltip')}
                >
                  <Edit3 className="h-4 w-4" />
                </button>
                <button
                  onClick={() => {
                    void handleShare();
                  }}
                  className="p-2 text-gray-400 dark:text-slate-500 hover:text-green-600 dark:hover:text-green-400 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                  aria-label={t('memory.detail.shareAria')}
                  title={t('memory.detail.shareTitle')}
                >
                  <Share2 className="h-4 w-4" />
                </button>
                <button
                  onClick={handleDownload}
                  className="p-2 text-gray-400 dark:text-slate-500 hover:text-purple-600 dark:hover:text-purple-400 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                  aria-label={t('memory.detail.downloadAria')}
                  title={t('memory.detail.downloadTitle')}
                >
                  <Download className="h-4 w-4" />
                </button>
              </>
            )}
            <button
              onClick={onClose}
              aria-label={t('memory.detail.closeAria')}
              className="p-2 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="p-6">
            <div className="mb-6">
              <div className="flex items-center space-x-3 mb-3">
                <span
                  className={`px-3 py-1 rounded-full text-sm font-medium ${getTypeColor(memory.content_type)}`}
                >
                  {memory.content_type}
                </span>
                {isEditing ? (
                  <input
                    type="text"
                    value={editedTitle}
                    onChange={(e) => {
                      setEditedTitle(e.target.value);
                    }}
                    className="flex-1 text-xl font-semibold text-gray-900 dark:text-white bg-white dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-md px-3 py-1 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder={t('memory.detail.titlePlaceholder')}
                    aria-label={t('memory.detail.editTitleAria', {
                      defaultValue: 'Edit memory title',
                    })}
                  />
                ) : (
                  <h3 className="text-xl font-semibold text-gray-900 dark:text-white">
                    {memory.title}
                  </h3>
                )}
              </div>

              <div className="flex items-center space-x-4 text-sm text-gray-500 dark:text-slate-400 mb-4">
                {memory.author_id && (
                  <div className="flex items-center space-x-1">
                    <User className="h-4 w-4" />
                    <span>
                      {t('memory.detail.userPrefix')} {memory.author_id}
                    </span>
                  </div>
                )}
                <div className="flex items-center space-x-1">
                  <Calendar className="h-4 w-4" />
                  <span>
                    {t('memory.detail.createdPrefix')} {formatDate(memory.created_at)}
                  </span>
                </div>
                {memory.updated_at !== memory.created_at && (
                  <div className="flex items-center space-x-1">
                    <Calendar className="h-4 w-4" />
                    <span>
                      {t('memory.detail.updatedPrefix')} {formatDate(memory.updated_at || '')}
                    </span>
                  </div>
                )}
              </div>
            </div>

            <div className="mb-6">
              <h4 className="text-lg font-medium text-gray-900 dark:text-white mb-3">
                {t('memory.detail.contentHeading')}
              </h4>
              {isEditing ? (
                <div>
                  <textarea
                    value={editedContent}
                    onChange={(e) => {
                      setEditedContent(e.target.value);
                    }}
                    className="w-full h-64 px-4 py-3 bg-white dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-gray-900 dark:text-slate-200 whitespace-pre-wrap leading-relaxed resize-y"
                    placeholder={t('memory.detail.contentPlaceholder')}
                    aria-label={t('memory.detail.editContentAria', {
                      defaultValue: 'Edit memory content',
                    })}
                  />
                  {error && (
                    <div className="mt-3 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900/30 rounded-md">
                      <p className="text-sm text-red-800 dark:text-red-300">{error}</p>
                    </div>
                  )}
                </div>
              ) : (
                <div className="bg-gray-50 dark:bg-slate-800 rounded-lg p-4 border border-gray-100 dark:border-slate-700">
                  <p className="text-gray-800 dark:text-slate-200 whitespace-pre-wrap leading-relaxed">
                    {memory.content}
                  </p>
                </div>
              )}
            </div>

            {hasEntities && (
              <div className="mb-6">
                <h4 className="text-lg font-medium text-gray-900 dark:text-white mb-3">
                  {t('memory.detail.entitiesHeading')}
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {memory.entities.map((entity, index) => (
                    <div
                      key={index}
                      className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-900/30 rounded-lg p-3"
                    >
                      <div className="flex items-center space-x-2 mb-1">
                        <Hash className="h-4 w-4 text-green-600 dark:text-green-400" />
                        <span className="font-medium text-green-800 dark:text-green-200">
                          {entity.name}
                        </span>
                        <span className="text-xs text-green-600 dark:text-green-300 bg-green-100 dark:bg-green-900/40 px-2 py-1 rounded-full">
                          {entity.type}
                        </span>
                      </div>
                      {Object.keys(entity.properties).length > 0 && (
                        <p className="text-sm text-green-700 dark:text-green-300">
                          {JSON.stringify(entity.properties)}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {hasRelationships && (
              <div className="mb-6">
                <h4 className="text-lg font-medium text-gray-900 dark:text-white mb-3">
                  {t('memory.detail.relationshipsHeading')}
                </h4>
                <div className="space-y-3">
                  {memory.relationships.map((relationship, index) => (
                    <div
                      key={index}
                      className="bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-900/30 rounded-lg p-3"
                    >
                      <div className="flex items-center space-x-3">
                        <div className="w-3 h-3 bg-purple-500 rounded-full"></div>
                        <div className="flex-1">
                          <div className="flex items-center space-x-2">
                            <span className="font-medium text-purple-800 dark:text-purple-200">
                              {relationship.source_id}
                            </span>
                            <span className="text-purple-600 dark:text-purple-400">→</span>
                            <span className="font-medium text-purple-800 dark:text-purple-200">
                              {relationship.target_id}
                            </span>
                          </div>
                          <div className="flex items-center space-x-2 mt-1">
                            <span className="text-xs text-purple-600 dark:text-purple-300 bg-purple-100 dark:bg-purple-900/40 px-2 py-1 rounded-full">
                              {relationship.type}
                            </span>
                            <span className="text-xs text-purple-500 dark:text-purple-400">
                              {t('memory.detail.confidencePrefix')} {relationship.confidence}
                            </span>
                          </div>
                        </div>
                      </div>
                      {Object.keys(relationship.properties).length > 0 && (
                        <p className="text-sm text-purple-700 dark:text-purple-300 mt-2">
                          {JSON.stringify(relationship.properties)}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {hasMetadata && (
              <div className="mb-6">
                <h4 className="text-lg font-medium text-gray-900 dark:text-white mb-3">
                  {t('memory.detail.metadataHeading')}
                </h4>
                <div className="bg-gray-50 dark:bg-slate-800 rounded-lg p-4 border border-gray-100 dark:border-slate-700">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {Object.entries(memory.metadata).map(([key, value]) => (
                      <div key={key} className="flex items-center space-x-2">
                        <Tag className="h-4 w-4 text-gray-400 dark:text-slate-500" />
                        <span className="text-sm font-medium text-gray-700 dark:text-slate-300">
                          {key}:
                        </span>
                        <span className="text-sm text-gray-600 dark:text-slate-400">
                          {formatMetadataValue(value)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            <div className="border-t border-gray-200 dark:border-slate-800 pt-4">
              <div className="flex items-center justify-between text-sm text-gray-500 dark:text-slate-400">
                <div className="flex items-center space-x-4">
                  <span>ID: {memory.id}</span>
                  <span>
                    {t('memory.detail.projectPrefix')} {memory.project_id}
                  </span>
                </div>
                <div className="flex items-center space-x-2">
                  <Eye className="h-4 w-4" />
                  <span>
                    {t('memory.detail.viewCountPrefix')} {getViewCount(memory.metadata)}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
