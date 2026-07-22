import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { App, Input, Tag, Dropdown, Breadcrumb, Tree } from 'antd';
import {
  Download,
  Eye,
  FilePlus,
  FileText,
  Folder,
  FolderOpen,
  FolderPlus,
  HardDrive,
  MoreVertical,
  Trash2,
  Upload,
  Image as ImageIcon,
  FileBox,
  Terminal,
  Code,
  Braces,
  File,
  Search as SearchIcon,
} from 'lucide-react';

import { instanceFileService } from '@/services/instanceFileService';

import {
  useLazyMessage,
  LazyAlert,
  LazyEmpty,
  LazySpin,
  LazyModal,
  LazyButton,
} from '@/components/ui/lazyAntd';

import { formatDate } from './utils/instanceUtils';

import type { MenuProps, TreeDataNode } from 'antd';

const { Search } = Input;

// Types for file system
interface FileNode {
  key: string;
  name: string;
  type: 'file' | 'folder';
  size: number | null;
  mime_type: string | null;
  modified_at: string;
  children?: FileNode[];
}

const getFileIcon = (
  node: FileNode
): React.ComponentType<{ size?: number; className?: string }> => {
  if (node.type === 'folder') return Folder;

  const ext = node.name.split('.').pop()?.toLowerCase();
  const mime = node.mime_type;

  if (mime?.startsWith('image/')) return ImageIcon;
  if (mime?.includes('pdf')) return FileBox;
  if (ext === 'py') return Terminal;
  if (ext === 'js' || ext === 'ts') return Code;
  if (ext === 'json') return Braces;
  if (ext === 'md') return FileText;
  if (ext === 'yaml' || ext === 'yml') return File;
  if (ext === 'csv') return FileText;
  if (ext === 'txt') return FileText;

  return FileText;
};

const formatFileSize = (bytes: number | null): string => {
  if (bytes === null) return '-';
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export const InstanceFiles: React.FC = () => {
  const { t } = useTranslation();
  const { instanceId } = useParams<{ instanceId: string }>();
  const messageApi = useLazyMessage();
  const { modal } = App.useApp();

  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [search, setSearch] = useState('');
  const [selectedNode, setSelectedNode] = useState<FileNode | null>(null);
  const [expandedKeys, setExpandedKeys] = useState<string[]>(['workspace']);
  const [isPreviewModalOpen, setIsPreviewModalOpen] = useState(false);
  const [previewContent, setPreviewContent] = useState<string>('');
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [createType, setCreateType] = useState<'file' | 'folder'>('file');
  const [createName, setCreateName] = useState('');
  const [createParentPath, setCreateParentPath] = useState('');

  const fetchFileTree = useCallback(async () => {
    if (!instanceId) return;
    setIsLoading(true);
    setLoadError(false);
    try {
      const response = await instanceFileService.listFiles(instanceId);
      setFileTree(response.tree);
    } catch {
      setLoadError(true);
      messageApi?.error(t('tenant.instances.files.fetchError'));
    } finally {
      setIsLoading(false);
    }
  }, [instanceId, messageApi, t]);

  useEffect(() => {
    void fetchFileTree();
  }, [fetchFileTree]);

  // Recursively filter tree nodes by search term, keeping parent folders if any descendant matches
  const filterTree = useCallback((nodes: FileNode[], term: string): FileNode[] => {
    if (!term) return nodes;
    const lowerTerm = term.toLowerCase();
    return nodes.reduce<FileNode[]>((acc, node) => {
      const nameMatches = node.name.toLowerCase().includes(lowerTerm);
      const filteredChildren = node.children ? filterTree(node.children, term) : [];
      if (nameMatches || filteredChildren.length > 0) {
        const newNode = { ...node };
        if (node.children) {
          newNode.children = filteredChildren;
        } else {
          delete newNode.children;
        }
        acc.push(newNode);
      }
      return acc;
    }, []);
  }, []);

  const filteredFileTree = useMemo(
    () => filterTree(fileTree, search),
    [fileTree, search, filterTree]
  );

  // Auto-expand all folders when searching so matched results are visible
  const effectiveExpandedKeys = useMemo(() => {
    if (!search) return expandedKeys;
    const keys: string[] = [];
    const collectFolderKeys = (nodes: FileNode[]) => {
      for (const node of nodes) {
        if (node.type === 'folder') {
          keys.push(node.key);
          if (node.children) collectFolderKeys(node.children);
        }
      }
    };
    collectFolderKeys(filteredFileTree);
    return keys;
  }, [search, expandedKeys, filteredFileTree]);

  const convertToTreeData = useCallback(
    (nodes: FileNode[]): TreeDataNode[] => {
      return nodes.map((node) => {
        const treeNode: TreeDataNode = {
          key: node.key,
          title: (
            <div className="flex min-w-0 items-center gap-2">
              {(() => {
                const Icon = getFileIcon(node);
                return <Icon size={16} className="shrink-0" />;
              })()}
              <span
                className={`truncate ${selectedNode?.key === node.key ? 'font-medium text-info-dark' : ''}`}
              >
                {node.name}
              </span>
            </div>
          ),
          isLeaf: node.type === 'file',
        };
        if (node.children && node.children.length > 0) {
          treeNode.children = convertToTreeData(node.children);
        }
        return treeNode;
      });
    },
    [selectedNode]
  );

  const findNodeByKey = useCallback((nodes: FileNode[], key: string): FileNode | null => {
    for (const node of nodes) {
      if (node.key === key) return node;
      if (node.children) {
        const found = findNodeByKey(node.children, key);
        if (found) return found;
      }
    }
    return null;
  }, []);

  const handleSelect = useCallback(
    (keys: React.Key[]) => {
      if (keys.length > 0) {
        const node = findNodeByKey(fileTree, keys[0] as string);
        setSelectedNode(node);
      }
    },
    [fileTree, findNodeByKey]
  );

  const handleExpand = useCallback((keys: React.Key[]) => {
    setExpandedKeys(keys as string[]);
  }, []);

  const handlePreview = useCallback(
    async (node: FileNode) => {
      if (!instanceId || node.type !== 'file') return;

      setIsPreviewLoading(true);
      setIsPreviewModalOpen(true);

      try {
        const response = await instanceFileService.previewFile(instanceId, node.key);
        setPreviewContent(response.content);
      } catch {
        messageApi?.error(t('tenant.instances.files.previewError'));
      } finally {
        setIsPreviewLoading(false);
      }
    },
    [instanceId, messageApi, t]
  );

  const handleDownload = useCallback(
    async (node: FileNode) => {
      if (!instanceId || node.type !== 'file') return;

      try {
        const blob = await instanceFileService.downloadFile(instanceId, node.key);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = node.name;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        messageApi?.success(t('tenant.instances.files.downloadSuccess'));
      } catch {
        messageApi?.error(t('tenant.instances.files.downloadError'));
      }
    },
    [instanceId, messageApi, t]
  );

  const handleDelete = useCallback(
    async (node: FileNode) => {
      if (!instanceId) return;

      setIsSubmitting(true);
      try {
        await instanceFileService.deleteFile(instanceId, node.key);
        messageApi?.success(t('tenant.instances.files.deleteSuccess'));
        setSelectedNode(null);
        void fetchFileTree();
      } catch {
        messageApi?.error(t('tenant.instances.files.deleteError'));
      } finally {
        setIsSubmitting(false);
      }
    },
    [instanceId, messageApi, t, fetchFileTree]
  );

  const handleCreate = useCallback(async () => {
    if (!instanceId || !createName.trim()) return;

    setIsSubmitting(true);
    try {
      await instanceFileService.createFile(
        instanceId,
        createParentPath ? `${createParentPath}/${createName}` : createName,
        createType
      );
      messageApi?.success(
        createType === 'folder'
          ? t('tenant.instances.files.createFolderSuccess')
          : t('tenant.instances.files.createFileSuccess')
      );
      setIsCreateModalOpen(false);
      setCreateName('');
      setCreateParentPath('');
      void fetchFileTree();
    } catch {
      messageApi?.error(t('tenant.instances.files.createError'));
    } finally {
      setIsSubmitting(false);
    }
  }, [instanceId, createName, createType, createParentPath, messageApi, t, fetchFileTree]);

  const handleUpload = useCallback(() => {
    if (!instanceId || isUploading) return;
    const input = document.createElement('input');
    input.type = 'file';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      setIsUploading(true);
      try {
        const directory = selectedNode?.type === 'folder' ? selectedNode.key : '';
        await instanceFileService.uploadFile(instanceId, file, directory);
        messageApi?.success(t('tenant.instances.files.uploadSuccess'));
        void fetchFileTree();
      } catch {
        messageApi?.error(t('tenant.instances.files.uploadError'));
      } finally {
        setIsUploading(false);
      }
    };
    input.click();
  }, [instanceId, isUploading, selectedNode, messageApi, t, fetchFileTree]);

  const getBreadcrumbItems = useCallback((key: string) => {
    const parts = key.split('/');
    return parts.map((part, index) => ({
      title: part,
      key: parts.slice(0, index + 1).join('/'),
    }));
  }, []);

  const contextMenuItems = useMemo<MenuProps['items']>(() => {
    if (!selectedNode) return [];

    const items: MenuProps['items'] = [];

    if (selectedNode.type === 'file') {
      items.push({
        key: 'preview',
        label: t('tenant.instances.files.preview'),
        icon: <Eye size={16} />,
        onClick: () => {
          void handlePreview(selectedNode);
        },
      });
      items.push({
        key: 'download',
        label: t('common.download'),
        icon: <Download size={16} />,
        onClick: () => {
          void handleDownload(selectedNode);
        },
      });
      items.push({ type: 'divider' });
    } else {
      items.push({
        key: 'newFile',
        label: t('tenant.instances.files.newFile'),
        icon: <FilePlus size={16} />,
        onClick: () => {
          setCreateType('file');
          setCreateParentPath(selectedNode.key);
          setCreateName('');
          setIsCreateModalOpen(true);
        },
      });
      items.push({
        key: 'newFolder',
        label: t('tenant.instances.files.newFolder'),
        icon: <FolderPlus size={16} />,
        onClick: () => {
          setCreateType('folder');
          setCreateParentPath(selectedNode.key);
          setCreateName('');
          setIsCreateModalOpen(true);
        },
      });
      items.push({ type: 'divider' });
    }

    items.push({
      key: 'delete',
      label: t('common.delete'),
      icon: <Trash2 size={16} />,
      danger: true,
      onClick: () => {
        modal.confirm({
          title: t('tenant.instances.files.deleteConfirm'),
          content:
            selectedNode.type === 'folder'
              ? t('tenant.instances.files.deleteFolderConfirmDesc')
              : t('tenant.instances.files.deleteFileConfirmDesc'),
          okText: t('common.delete'),
          cancelText: t('common.cancel'),
          okButtonProps: { danger: true },
          onOk: () => handleDelete(selectedNode),
        });
      },
    });

    return items;
  }, [selectedNode, t, modal, handlePreview, handleDownload, handleDelete]);

  if (!instanceId) return null;

  return (
    <div className="flex flex-col gap-6">
      {/* Toolbar */}
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
            {t('tenant.instances.files.title')}
          </h2>
          <p className="text-sm text-text-muted">{t('tenant.instances.files.description')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <LazyButton
            onClick={() => {
              setCreateType('folder');
              setCreateParentPath('');
              setCreateName('');
              setIsCreateModalOpen(true);
            }}
            icon={<FolderPlus size={16} />}
          >
            {t('tenant.instances.files.newFolder')}
          </LazyButton>
          <LazyButton
            onClick={() => {
              setCreateType('file');
              setCreateParentPath('');
              setCreateName('');
              setIsCreateModalOpen(true);
            }}
            icon={<FilePlus size={16} />}
          >
            {t('tenant.instances.files.newFile')}
          </LazyButton>
          <LazyButton
            type="primary"
            onClick={handleUpload}
            loading={isUploading}
            icon={<Upload size={16} />}
          >
            {t('tenant.instances.files.upload')}
          </LazyButton>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-warning-bg dark:bg-warning-bg-dark rounded-lg">
              <Folder size={16} className="text-warning-dark dark:text-warning-light" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-text-primary dark:text-text-inverse">
                {fileTree.length}
              </p>
              <p className="text-xs text-text-muted dark:text-text-muted">
                {t('tenant.instances.files.totalFolders')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-info-bg dark:bg-info-bg-dark rounded-lg">
              <FileText size={16} className="text-info-dark dark:text-info-light" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-text-primary dark:text-text-inverse">
                {fileTree.reduce((count, node) => {
                  const countFiles = (n: FileNode): number => {
                    if (n.type === 'file') return 1;
                    return (n.children || []).reduce((sum, child) => sum + countFiles(child), 0);
                  };
                  return count + countFiles(node);
                }, 0)}
              </p>
              <p className="text-xs text-text-muted dark:text-text-muted">
                {t('tenant.instances.files.totalFiles')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-success-bg dark:bg-success-bg-dark rounded-lg">
              <HardDrive size={16} className="text-success-dark dark:text-success-light" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-text-primary dark:text-text-inverse">
                {formatFileSize(
                  fileTree.reduce((total, node) => {
                    const getTotalSize = (n: FileNode): number => {
                      if (n.type === 'file') return n.size || 0;
                      return (n.children || []).reduce(
                        (sum, child) => sum + getTotalSize(child),
                        0
                      );
                    };
                    return total + getTotalSize(node);
                  }, 0)
                )}
              </p>
              <p className="text-xs text-text-muted dark:text-text-muted">
                {t('tenant.instances.files.totalSize')}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Main content - Split view */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* File Tree */}
        <div className="lg:col-span-1">
          <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark overflow-hidden">
            <div className="p-3 border-b border-border-light dark:border-border-dark">
              <Search
                placeholder={t('tenant.instances.files.searchPlaceholder')}
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                }}
                allowClear
                enterButton={
                  <>
                    <span className="sr-only">{t('common.search', 'Search')}</span>
                    <SearchIcon size={16} aria-hidden="true" />
                  </>
                }
              />
            </div>
            <div className="p-2 max-h-[500px] overflow-y-auto">
              {isLoading ? (
                <div className="flex justify-center py-8">
                  <LazySpin />
                </div>
              ) : loadError ? (
                <div className="py-8 flex flex-col items-center gap-3 px-4">
                  <LazyAlert
                    type="error"
                    showIcon
                    message={t('tenant.instances.files.fetchError')}
                  />
                  <LazyButton
                    size="small"
                    onClick={() => {
                      void fetchFileTree();
                    }}
                  >
                    {t('common.retry', 'Retry')}
                  </LazyButton>
                </div>
              ) : filteredFileTree.length === 0 ? (
                <div className="py-8">
                  <LazyEmpty
                    description={
                      search
                        ? t('tenant.instances.files.noSearchResults')
                        : t('tenant.instances.files.noFiles')
                    }
                  />
                </div>
              ) : (
                <Tree
                  treeData={convertToTreeData(filteredFileTree)}
                  selectedKeys={selectedNode ? [selectedNode.key] : []}
                  expandedKeys={effectiveExpandedKeys}
                  onSelect={handleSelect}
                  onExpand={handleExpand}
                  showIcon={false}
                  blockNode
                />
              )}
            </div>
          </div>
        </div>

        {/* File Details */}
        <div className="lg:col-span-2">
          <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark overflow-hidden">
            {selectedNode ? (
              <>
                {/* Header with path */}
                <div className="p-4 border-b border-border-light dark:border-border-dark flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {(() => {
                      const Icon = getFileIcon(selectedNode);
                      return <Icon size={16} className="text-text-muted" />;
                    })()}
                    <Breadcrumb items={getBreadcrumbItems(selectedNode.key)} className="text-sm" />
                  </div>
                  <Dropdown menu={{ items: contextMenuItems ?? [] }} trigger={['click']}>
                    <LazyButton
                      type="text"
                      icon={<MoreVertical size={16} />}
                      aria-label={t('common.moreActions', 'More actions')}
                    />
                  </Dropdown>
                </div>

                {/* File info */}
                <div className="p-4 space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <span className="block text-xs font-medium text-text-muted dark:text-text-muted mb-1">
                        {t('tenant.instances.files.colType')}
                      </span>
                      <p className="text-sm text-text-primary dark:text-text-inverse">
                        <Tag>
                          {selectedNode.type === 'folder'
                            ? t('tenant.instances.files.typeFolder', 'Folder')
                            : t('tenant.instances.files.typeFile', 'File')}
                        </Tag>
                        {selectedNode.mime_type && (
                          <span className="ml-2 text-text-muted">{selectedNode.mime_type}</span>
                        )}
                      </p>
                    </div>
                    <div>
                      <span className="block text-xs font-medium text-text-muted dark:text-text-muted mb-1">
                        {t('tenant.instances.files.colSize')}
                      </span>
                      <p className="text-sm text-text-primary dark:text-text-inverse">
                        {formatFileSize(selectedNode.size)}
                      </p>
                    </div>
                    <div className="col-span-2">
                      <span className="block text-xs font-medium text-text-muted dark:text-text-muted mb-1">
                        {t('tenant.instances.files.colModified')}
                      </span>
                      <p className="text-sm text-text-primary dark:text-text-inverse">
                        {formatDate(selectedNode.modified_at)}
                      </p>
                    </div>
                  </div>

                  {selectedNode.type === 'file' && (
                    <div className="flex gap-2 pt-2">
                      <LazyButton
                        type="primary"
                        icon={<Eye size={16} />}
                        onClick={() => {
                          void handlePreview(selectedNode);
                        }}
                      >
                        {t('tenant.instances.files.preview')}
                      </LazyButton>
                      <LazyButton
                        icon={<Download size={16} />}
                        onClick={() => {
                          void handleDownload(selectedNode);
                        }}
                      >
                        {t('common.download')}
                      </LazyButton>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="flex flex-col items-center justify-center py-20 text-text-muted dark:text-text-muted">
                <FolderOpen size={48} className="mb-3" />
                <p>{t('tenant.instances.files.selectFile')}</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Preview Modal */}
      <LazyModal
        title={selectedNode?.name || t('tenant.instances.files.preview')}
        open={isPreviewModalOpen}
        onCancel={() => {
          setIsPreviewModalOpen(false);
        }}
        footer={null}
        width={700}
      >
        <div className="max-h-[500px] overflow-y-auto">
          {isPreviewLoading ? (
            <div className="flex justify-center py-8">
              <LazySpin />
            </div>
          ) : (
            <pre className="bg-surface-muted dark:bg-surface-dark-alt p-4 rounded-lg text-sm overflow-x-auto font-mono">
              {previewContent}
            </pre>
          )}
        </div>
      </LazyModal>

      {/* Create Modal */}
      <LazyModal
        title={
          createType === 'folder'
            ? t('tenant.instances.files.newFolder')
            : t('tenant.instances.files.newFile')
        }
        open={isCreateModalOpen}
        onOk={() => {
          void handleCreate();
        }}
        onCancel={() => {
          setIsCreateModalOpen(false);
          setCreateName('');
          setCreateParentPath('');
        }}
        confirmLoading={isSubmitting}
        okButtonProps={{ disabled: !createName.trim() }}
      >
        <div className="space-y-4 py-2">
          {createParentPath && (
            <div>
              <label
                htmlFor="create-parent-path"
                className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
              >
                {t('tenant.instances.files.parentFolder')}
              </label>
              <Input id="create-parent-path" value={createParentPath} disabled />
            </div>
          )}
          <div>
            <label
              htmlFor="create-file-name"
              className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
            >
              {createType === 'folder'
                ? t('tenant.instances.files.folderName')
                : t('tenant.instances.files.fileName')}
            </label>
            <Input
              id="create-file-name"
              value={createName}
              onChange={(e) => {
                setCreateName(e.target.value);
              }}
              placeholder={
                createType === 'folder'
                  ? t('tenant.instances.files.folderNamePlaceholder')
                  : t('tenant.instances.files.fileNamePlaceholder')
              }
              autoFocus
            />
          </div>
        </div>
      </LazyModal>
    </div>
  );
};
