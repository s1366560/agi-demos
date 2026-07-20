import { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Brain, AlertCircle, Type, Hash, Settings } from 'lucide-react';

import { AppModal } from '@/components/common';

import { useMemoryStore } from '../stores/memory';
import { useProjectStore } from '../stores/project';

import type { Entity, Relationship } from '../types/memory';

interface MemoryCreateModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: (() => void) | undefined;
}

type MemoryContentType = 'text' | 'document' | 'image' | 'video';

interface MemoryFormMetadata {
  enable_search?: boolean | undefined;
  enable_graph?: boolean | undefined;
  tags?: string[] | undefined;
  [key: string]: unknown;
}

interface MemoryFormData {
  title: string;
  content: string;
  content_type: MemoryContentType;
  author_id: string;
  metadata: MemoryFormMetadata;
}

const CONTENT_TYPES = new Set<MemoryContentType>(['text', 'document', 'image', 'video']);

const createInitialFormData = (): MemoryFormData => ({
  title: '',
  content: '',
  content_type: 'text',
  author_id: '',
  metadata: {},
});

const toMemoryContentType = (value: string): MemoryContentType =>
  CONTENT_TYPES.has(value as MemoryContentType) ? (value as MemoryContentType) : 'text';

export const MemoryCreateModal: React.FC<MemoryCreateModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  const { t } = useTranslation();
  const { createMemory, extractEntities, extractRelationships, isLoading, error } =
    useMemoryStore();
  const { currentProject } = useProjectStore();

  const [formData, setFormData] = useState<MemoryFormData>(() => createInitialFormData());

  const [extractedEntities, setExtractedEntities] = useState<Entity[]>([]);
  const [extractedRelationships, setExtractedRelationships] = useState<Relationship[]>([]);
  const [activeTab, setActiveTab] = useState<'basic' | 'extraction' | 'advanced'>('basic');
  const [isExtracting, setIsExtracting] = useState(false);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!currentProject) return;

    try {
      const memoryData = {
        ...formData,
        entities: extractedEntities,
        relationships: extractedRelationships,
        project_id: currentProject.id,
      };

      await createMemory(currentProject.id, memoryData);
      onSuccess?.();
      onClose();
      resetForm();
    } catch (_error) {
      // Error is handled in store
    }
  };

  const handleExtractEntities = async () => {
    if (!currentProject || !formData.content.trim()) return;

    setIsExtracting(true);
    try {
      const entities = await extractEntities(currentProject.id, formData.content);
      setExtractedEntities(entities);
    } catch (_error) {
      // Error is handled in store
    } finally {
      setIsExtracting(false);
    }
  };

  const handleExtractRelationships = async () => {
    if (!currentProject || !formData.content.trim()) return;

    setIsExtracting(true);
    try {
      const relationships = await extractRelationships(currentProject.id, formData.content);
      setExtractedRelationships(relationships);
    } catch (_error) {
      // Error is handled in store
    } finally {
      setIsExtracting(false);
    }
  };

  const resetForm = () => {
    setFormData({
      ...createInitialFormData(),
    });
    setExtractedEntities([]);
    setExtractedRelationships([]);
    setActiveTab('basic');
  };

  const handleClose = () => {
    onClose();
    resetForm();
  };

  if (!isOpen) return null;

  return (
    <AppModal
      open={isOpen}
      onClose={handleClose}
      title={t('memory.create.title')}
      ariaLabel={t('memory.create.closeAria', {
        defaultValue: 'Close create memory dialog',
      })}
      size="xl"
      footer={
        <>
          <button
            type="button"
            onClick={handleClose}
            className="flex-1 px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
            disabled={isLoading}
          >
            {t('memory.create.cancel')}
          </button>
          <button
            type="submit"
            form="memory-form"
            className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={isLoading || !formData.title.trim() || !formData.content.trim()}
          >
            {isLoading ? (
              <div className="flex items-center justify-center space-x-2">
                <div className="animate-spin motion-reduce:animate-none rounded-full h-4 w-4 border-b-2 border-white"></div>
                <span>{t('memory.create.creating')}</span>
              </div>
            ) : (
              t('memory.create.submit')
            )}
          </button>
        </>
      }
    >
      <div className="flex items-center space-x-2 mb-4">
        <Brain className="h-5 w-5 text-blue-600 dark:text-blue-400" />
      </div>

      <div className="border-b border-gray-200 dark:border-slate-800">
        <nav className="flex space-x-8 px-6">
          <button
            type="button"
            onClick={() => {
              setActiveTab('basic');
            }}
            className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 ${
              activeTab === 'basic'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200'
            }`}
          >
            <div className="flex items-center space-x-2">
              <Type className="h-4 w-4" />
              <span>{t('memory.create.tabBasic')}</span>
            </div>
          </button>
          <button
              type="button"
              onClick={() => {
                setActiveTab('extraction');
              }}
              className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 ${
                activeTab === 'extraction'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-2">
                <Hash className="h-4 w-4" />
                <span>{t('memory.create.tabExtraction')}</span>
              </div>
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTab('advanced');
              }}
              className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 ${
                activeTab === 'advanced'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-2">
                <Settings className="h-4 w-4" />
                <span>{t('memory.create.tabAdvanced')}</span>
              </div>
            </button>
          </nav>
        </div>

        <form
          onSubmit={(event) => {
            void handleSubmit(event);
          }}
          className="flex-1 overflow-y-auto"
          id="memory-form"
        >
          <div className="p-6 space-y-4">
            {error && (
              <div
                className="flex items-center space-x-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900/30 rounded-md"
                role="alert"
                aria-live="assertive"
              >
                <AlertCircle
                  className="h-4 w-4 text-red-600 dark:text-red-400"
                  aria-hidden="true"
                />
                <span className="text-sm text-red-800 dark:text-red-300">{error}</span>
              </div>
            )}

            {activeTab === 'basic' && (
              <>
                <div>
                  <label
                    htmlFor="memory-create-title"
                    className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                  >
                    {t('memory.create.titleLabel')}
                  </label>
                  <input
                    type="text"
                    id="memory-create-title"
                    value={formData.title}
                    onChange={(e) => {
                      setFormData({ ...formData, title: e.target.value });
                    }}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                    placeholder={t('memory.create.titlePlaceholder')}
                    required
                    disabled={isLoading}
                    aria-required="true"
                  />
                </div>

                <div>
                  <label
                    htmlFor="memory-create-content"
                    className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                  >
                    {t('memory.create.contentLabel')}
                  </label>
                  <textarea
                    id="memory-create-content"
                    value={formData.content}
                    onChange={(e) => {
                      setFormData({ ...formData, content: e.target.value });
                    }}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                    placeholder={t('memory.create.contentPlaceholder')}
                    rows={6}
                    required
                    disabled={isLoading}
                    aria-required="true"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label
                      htmlFor="memory-create-type"
                      className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                    >
                      {t('memory.create.typeLabel')}
                    </label>
                    <select
                      id="memory-create-type"
                      value={formData.content_type}
                      onChange={(e) => {
                        setFormData({
                          ...formData,
                          content_type: toMemoryContentType(e.target.value),
                        });
                      }}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
                      disabled={isLoading}
                    >
                      <option value="text">{t('memory.create.typeText')}</option>
                      <option value="document">{t('memory.create.typeDocument')}</option>
                      <option value="image">{t('memory.create.typeImage')}</option>
                      <option value="video">{t('memory.create.typeVideo')}</option>
                    </select>
                  </div>

                  <div>
                    <label
                      htmlFor="memory-create-author"
                      className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                    >
                      {t('memory.create.authorLabel')}
                    </label>
                    <input
                      type="text"
                      id="memory-create-author"
                      value={formData.author_id}
                      onChange={(e) => {
                        setFormData({ ...formData, author_id: e.target.value });
                      }}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                      placeholder={t('memory.create.authorPlaceholder')}
                      disabled={isLoading}
                      aria-describedby="memory-create-author-help"
                    />
                    <span
                      id="memory-create-author-help"
                      className="text-xs text-gray-500 dark:text-slate-400"
                    >
                      {t('memory.create.authorHelp')}
                    </span>
                  </div>
                </div>
              </>
            )}

            {activeTab === 'extraction' && (
              <>
                <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-900/30 rounded-md p-4 mb-4">
                  <div className="flex items-center space-x-2 mb-2">
                    <Brain className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                    <span className="text-sm font-medium text-blue-800 dark:text-blue-200">
                      {t('memory.create.extractionHeading')}
                    </span>
                  </div>
                  <p className="text-sm text-blue-700 dark:text-blue-300">
                    {t('memory.create.extractionHint')}
                  </p>
                </div>

                <div className="flex space-x-4 mb-4">
                  <button
                    type="button"
                    onClick={() => {
                      void handleExtractEntities();
                    }}
                    disabled={!formData.content.trim() || isExtracting || isLoading}
                    className="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isExtracting ? (
                      <div className="flex items-center space-x-2">
                        <div className="animate-spin motion-reduce:animate-none rounded-full h-4 w-4 border-b-2 border-white"></div>
                        <span>{t('memory.create.extracting')}</span>
                      </div>
                    ) : (
                      t('memory.create.extractEntities')
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void handleExtractRelationships();
                    }}
                    disabled={!formData.content.trim() || isExtracting || isLoading}
                    className="px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isExtracting ? (
                      <div className="flex items-center space-x-2">
                        <div className="animate-spin motion-reduce:animate-none rounded-full h-4 w-4 border-b-2 border-white"></div>
                        <span>{t('memory.create.extracting')}</span>
                      </div>
                    ) : (
                      t('memory.create.extractRelationships')
                    )}
                  </button>
                </div>

                {extractedEntities.length > 0 && (
                  <div className="mb-4">
                    <h4 className="text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
                      {t('memory.create.extractedEntitiesHeading')}
                    </h4>
                    <div className="grid grid-cols-2 gap-2">
                      {extractedEntities.map((entity, index) => (
                        <div
                          key={index}
                          className="flex items-center space-x-2 p-2 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-900/30 rounded-md"
                        >
                          <div className="w-2 h-2 bg-green-500 rounded-full"></div>
                          <span className="text-sm text-green-800 dark:text-green-200">
                            {entity.name}
                          </span>
                          <span className="text-xs text-green-600 dark:text-green-400">
                            ({entity.type})
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {extractedRelationships.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
                      {t('memory.create.extractedRelationshipsHeading')}
                    </h4>
                    <div className="space-y-2">
                      {extractedRelationships.map((relationship, index) => (
                        <div
                          key={index}
                          className="flex items-center space-x-2 p-2 bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-900/30 rounded-md"
                        >
                          <div className="w-2 h-2 bg-purple-500 rounded-full"></div>
                          <span className="text-sm text-purple-800 dark:text-purple-200">
                            {relationship.source_id} → {relationship.target_id}
                          </span>
                          <span className="text-xs text-purple-600 dark:text-purple-400">
                            ({relationship.type})
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}

            {activeTab === 'advanced' && (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
                    {t('memory.create.metadataLabel')}
                  </label>
                  <div className="space-y-3">
                    <div className="flex items-center space-x-2">
                      <input
                        type="checkbox"
                        id="enable_search"
                        checked={formData.metadata.enable_search ?? true}
                        onChange={(e) => {
                          setFormData({
                            ...formData,
                            metadata: {
                              ...formData.metadata,
                              enable_search: e.target.checked,
                            },
                          });
                        }}
                        className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 dark:border-slate-600 rounded bg-white dark:bg-slate-800"
                        disabled={isLoading}
                      />
                      <label
                        htmlFor="enable_search"
                        className="text-sm text-gray-700 dark:text-slate-300"
                      >
                        {t('memory.create.enableSearch')}
                      </label>
                    </div>
                    <div className="flex items-center space-x-2">
                      <input
                        type="checkbox"
                        id="enable_graph"
                        checked={formData.metadata.enable_graph ?? true}
                        onChange={(e) => {
                          setFormData({
                            ...formData,
                            metadata: {
                              ...formData.metadata,
                              enable_graph: e.target.checked,
                            },
                          });
                        }}
                        className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 dark:border-slate-600 rounded bg-white dark:bg-slate-800"
                        disabled={isLoading}
                      />
                      <label
                        htmlFor="enable_graph"
                        className="text-sm text-gray-700 dark:text-slate-300"
                      >
                        {t('memory.create.enableGraph')}
                      </label>
                    </div>
                  </div>
                </div>

                <div>
                  <label
                    htmlFor="memory-create-tags"
                    className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                  >
                    {t('memory.create.tagsLabel')}
                  </label>
                  <input
                    type="text"
                    id="memory-create-tags"
                    value={formData.metadata.tags?.join(', ') ?? ''}
                    onChange={(e) => {
                      setFormData({
                        ...formData,
                        metadata: {
                          ...formData.metadata,
                          tags: e.target.value
                            .split(',')
                            .map((tag) => tag.trim())
                            .filter(Boolean),
                        },
                      });
                    }}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                    placeholder={t('memory.create.tagsPlaceholder')}
                    disabled={isLoading}
                    aria-describedby="memory-create-tags-help"
                  />
                  <span
                    id="memory-create-tags-help"
                    className="text-xs text-gray-500 dark:text-slate-400"
                  >
                    {t('memory.create.tagsHelp')}
                  </span>
                </div>
              </>
            )}
          </div>
        </form>
    </AppModal>
  );
};
