import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import { Input, Tag, Dropdown, Button as AntButton, Breadcrumb, Tree, Modal } from 'antd';
import { ArrowLeft, Download, Eye, FilePlus, FileText, Folder, FolderOpen, FolderPlus, HardDrive, MoreVertical, Trash2, Upload, Image as ImageIcon, FileBox, Terminal, Code, Braces, File } from 'lucide-react';

import { useLazyMessage, LazyEmpty, LazySpin, LazyModal } from '@/components/ui/lazyAntd';

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

// Mock data for demonstration
const mockFileTree: FileNode[] = [
  {
    key: 'workspace',
    name: 'workspace',
    type: 'folder',
    size: null,
    mime_type: null,
    modified_at: new Date(Date.now() - 86400000).toISOString(),
    children: [
      {
        key: 'workspace/src',
        name: 'src',
        type: 'folder',
        size: null,
        mime_type: null,
        modified_at: new Date(Date.now() - 86400000).toISOString(),
        children: [
          {
            key: 'workspace/src/main.py',
            name: 'main.py',
            type: 'file',
            size: 2048,
            mime_type: 'text/x-python',
            modified_at: new Date(Date.now() - 3600000).toISOString(),
          },
          {
            key: 'workspace/src/utils.py',
            name: 'utils.py',
            type: 'file',
            size: 1024,
            mime_type: 'text/x-python',
            modified_at: new Date(Date.now() - 7200000).toISOString(),
          },
          {
            key: 'workspace/src/config',
            name: 'config',
            type: 'folder',
            size: null,
            mime_type: null,
            modified_at: new Date(Date.now() - 86400000).toISOString(),
            children: [
              {
                key: 'workspace/src/config/settings.yaml',
                name: 'settings.yaml',
                type: 'file',
                size: 512,
                mime_type: 'application/x-yaml',
                modified_at: new Date(Date.now() - 172800000).toISOString(),
              },
            ],
          },
        ],
      },
      {
        key: 'workspace/data',
        name: 'data',
        type: 'folder',
        size: null,
        mime_type: null,
        modified_at: new Date(Date.now() - 86400000).toISOString(),
        children: [
          {
            key: 'workspace/data/input.json',
            name: 'input.json',
            type: 'file',
            size: 4096,
            mime_type: 'application/json',
            modified_at: new Date(Date.now() - 259200000).toISOString(),
          },
          {
            key: 'workspace/data/output.csv',
            name: 'output.csv',
            type: 'file',
            size: 8192,
            mime_type: 'text/csv',
            modified_at: new Date(Date.now() - 345600000).toISOString(),
          },
        ],
      },
      {
        key: 'workspace/README.md',
        name: 'README.md',
        type: 'file',
        size: 256,
        mime_type: 'text/markdown',
        modified_at: new Date(Date.now() - 604800000).toISOString(),
      },
      {
        key: 'workspace/requirements.txt',
        name: 'requirements.txt',
        type: 'file',
        size: 128,
        mime_type: 'text/plain',
        modified_at: new Date(Date.now() - 604800000).toISOString(),
      },
    ],
  },
];

const getFileIcon = (node: FileNode): React.ComponentType<{ size?: number; className?: string }> => {
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
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export const InstanceFiles: React.FC = () => {
  const { t } = useTranslation();
  const { instanceId } = useParams<{ instanceId: string }>();
  const navigate = useNavigate();
  const message = useLazyMessage();

  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
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
    try {
      // TODO: Replace with actual API call when backend endpoint is available
      // const response = await httpClient.get<{ tree: FileNode[] }>(
      //   `/instances/${instanceId}/files`
      // );
      // setFileTree(response.tree);

      await new Promise((resolve) => setTimeout(resolve, 500));
      setFileTree(mockFileTree);
    } catch (error) {
      console.error('Failed to fetch file tree:', error);
      message?.error(t('tenant.instances.files.fetchError'));
    } finally {
      setIsLoading(false);
    }
  }, [instanceId, message, t]);

  useEffect(() => {
    fetchFileTree();
  }, [fetchFileTree]);

  const convertToTreeData = useCallback(
    (nodes: FileNode[]): TreeDataNode[] => {
      return nodes.map((node) => {
        const treeNode: TreeDataNode = {
          key: node.key,
          title: (
            <div className="flex items-center gap-2">
              {(() => { const Icon = getFileIcon(node); return <Icon size={16} />; })()}
              <span className={selectedNode?.key === node.key ? 'font-medium text-blue-600' : ''}>
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
      if (node.type !== 'file') return;

      setIsPreviewLoading(true);
      setIsPreviewModalOpen(true);

      try {
        // TODO: Replace with actual API call
        // const response = await httpClient.get<FileContent>(
        //   `/instances/${instanceId}/files/${encodeURIComponent(node.key)}/content`
        // );
        // setPreviewContent(response.content);

        await new Promise((resolve) => setTimeout(resolve, 500));

        // Mock content based on file type
        const ext = node.name.split('.').pop()?.toLowerCase();
        if (ext === 'py') {
          setPreviewContent(
            `# ${node.name}\n\ndef main():\n    print("Hello, World!")\n\nif __name__ == "__main__":\n    main()`
          );
        } else if (ext === 'json') {
          setPreviewContent('{\n  "name": "example",\n  "version": "1.0.0"\n}');
        } else if (ext === 'md') {
          setPreviewContent(`# Project Title\n\nThis is a sample README file.`);
        } else if (ext === 'yaml' || ext === 'yml') {
          setPreviewContent('app:\n  name: myapp\n  version: 1.0.0\ndebug: false');
        } else {
          setPreviewContent(`Content of ${node.name}`);
        }
      } catch (error) {
        console.error('Failed to fetch file content:', error);
        message?.error(t('tenant.instances.files.previewError'));
      } finally {
        setIsPreviewLoading(false);
      }
    },
    [message, t]
  );

  const handleDownload = useCallback(
    async (node: FileNode) => {
      if (node.type !== 'file') return;

      try {
        // TODO: Replace with actual API call
        // const blob = await httpClient.get(
        //   `/instances/${instanceId}/files/${encodeURIComponent(node.key)}/download`,
        //   { responseType: 'blob' }
        // );
        // const url = URL.createObjectURL(blob);
        // const a = document.createElement('a');
        // a.href = url;
        // a.download = node.name;
        // a.click();

        message?.success(t('tenant.instances.files.downloadSuccess'));
      } catch (error) {
        console.error('Failed to download file:', error);
        message?.error(t('tenant.instances.files.downloadError'));
      }
    },
    [message, t]
  );

  const handleDelete = useCallback(
    async (node: FileNode) => {
      if (!instanceId) return;
      // Log for debugging (node is used in actual API call)
      console.debug('Deleting node:', node.key);

      setIsSubmitting(true);
      try {
        // TODO: Replace with actual API call
        // await httpClient.delete(`/instances/${instanceId}/files/${encodeURIComponent(node.key)}`);

        await new Promise((resolve) => setTimeout(resolve, 500));
        message?.success(t('tenant.instances.files.deleteSuccess'));
        setSelectedNode(null);
        fetchFileTree();
      } catch (error) {
        console.error('Failed to delete:', error);
        message?.error(t('tenant.instances.files.deleteError'));
      } finally {
        setIsSubmitting(false);
      }
    },
    [instanceId, message, t, fetchFileTree]
  );

  const handleCreate = useCallback(async () => {
    if (!instanceId || !createName.trim()) return;

    setIsSubmitting(true);
    try {
      // TODO: Replace with actual API call
      // await httpClient.post(`/instances/${instanceId}/files`, {
      //   path: createParentPath ? `${createParentPath}/${createName}` : createName,
      //   type: createType,
      // });

      await new Promise((resolve) => setTimeout(resolve, 500));
      message?.success(
        createType === 'folder'
          ? t('tenant.instances.files.createFolderSuccess')
          : t('tenant.instances.files.createFileSuccess')
      );
      setIsCreateModalOpen(false);
      setCreateName('');
      setCreateParentPath('');
      fetchFileTree();
    } catch (error) {
      console.error('Failed to create:', error);
      message?.error(t('tenant.instances.files.createError'));
    } finally {
      setIsSubmitting(false);
    }
  }, [instanceId, createName, createType, createParentPath, message, t, fetchFileTree]);

  const handleUpload = useCallback(() => {
    // TODO: Implement file upload
    message?.info(t('tenant.instances.files.uploadInfo'));
  }, [message, t]);

  const handleGoBack = useCallback(() => {
    navigate(-1);
  }, [navigate]);

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
        onClick: () => handlePreview(selectedNode),
      });
      items.push({
        key: 'download',
        label: t('common.download'),
        icon: <Download size={16} />,
        onClick: () => handleDownload(selectedNode),
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
        Modal.confirm({
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
  }, [selectedNode, t, handlePreview, handleDownload, handleDelete]);

  if (!instanceId) return null;

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <button
          onClick={handleGoBack}
          type="button"
          className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 mb-3"
        >
          <ArrowLeft size={16} />
          {t('common.back')}
        </button>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
              {t('tenant.instances.files.title')}
            </h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {t('tenant.instances.files.description')}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                setCreateType('folder');
                setCreateParentPath('');
                setCreateName('');
                setIsCreateModalOpen(true);
              }}
              type="button"
              className="inline-flex items-center gap-2 px-3 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors text-sm font-medium"
            >
              <FolderPlus size={16} />
              {t('tenant.instances.files.newFolder')}
            </button>
            <button
              onClick={() => {
                setCreateType('file');
                setCreateParentPath('');
                setCreateName('');
                setIsCreateModalOpen(true);
              }}
              type="button"
              className="inline-flex items-center gap-2 px-3 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors text-sm font-medium"
            >
              <FilePlus size={16} />
              {t('tenant.instances.files.newFile')}
            </button>
            <button
              onClick={handleUpload}
              type="button"
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
            >
              <Upload size={16} />
              {t('tenant.instances.files.upload')}
            </button>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-amber-100 dark:bg-amber-900/30 rounded-lg">
              <Folder size={16} className="text-amber-600 dark:text-amber-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {fileTree.length}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.instances.files.totalFolders')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
              <FileText size={16} className="text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {fileTree.reduce((count, node) => {
                  const countFiles = (n: FileNode): number => {
                    if (n.type === 'file') return 1;
                    return (n.children || []).reduce((sum, child) => sum + countFiles(child), 0);
                  };
                  return count + countFiles(node);
                }, 0)}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.instances.files.totalFiles')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-green-100 dark:bg-green-900/30 rounded-lg">
              <HardDrive size={16} className="text-green-600 dark:text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
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
              <p className="text-xs text-slate-500 dark:text-slate-400">
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
          <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
            <div className="p-3 border-b border-slate-200 dark:border-slate-700">
              <Search
                placeholder={t('tenant.instances.files.searchPlaceholder')}
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                }}
                allowClear
              />
            </div>
            <div className="p-2 max-h-[500px] overflow-y-auto">
              {isLoading ? (
                <div className="flex justify-center py-8">
                  <LazySpin />
                </div>
              ) : fileTree.length === 0 ? (
                <div className="py-8">
                  <LazyEmpty description={t('tenant.instances.files.noFiles')} />
                </div>
              ) : (
                <Tree
                  treeData={convertToTreeData(fileTree)}
                  selectedKeys={selectedNode ? [selectedNode.key] : []}
                  expandedKeys={expandedKeys}
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
          <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
            {selectedNode ? (
              <>
                {/* Header with path */}
                <div className="p-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {(() => { const Icon = getFileIcon(selectedNode); return <Icon size={16} className="text-slate-400" />; })()}
                    <Breadcrumb items={getBreadcrumbItems(selectedNode.key)} className="text-sm" />
                  </div>
                  <Dropdown menu={{ items: contextMenuItems ?? [] }} trigger={['click']}>
                    <AntButton
                      type="text"
                      icon={<MoreVertical size={16} />}
                    />
                  </Dropdown>
                </div>

                {/* File info */}
                <div className="p-4 space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                        {t('tenant.instances.files.colType')}
                      </label>
                      <p className="text-sm text-slate-900 dark:text-slate-100">
                        <Tag>{selectedNode.type === 'folder' ? 'Folder' : 'File'}</Tag>
                        {selectedNode.mime_type && (
                          <span className="ml-2 text-slate-500">{selectedNode.mime_type}</span>
                        )}
                      </p>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                        {t('tenant.instances.files.colSize')}
                      </label>
                      <p className="text-sm text-slate-900 dark:text-slate-100">
                        {formatFileSize(selectedNode.size)}
                      </p>
                    </div>
                    <div className="col-span-2">
                      <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                        {t('tenant.instances.files.colModified')}
                      </label>
                      <p className="text-sm text-slate-900 dark:text-slate-100">
                        {new Date(selectedNode.modified_at).toLocaleString()}
                      </p>
                    </div>
                  </div>

                  {selectedNode.type === 'file' && (
                    <div className="flex gap-2 pt-2">
                      <AntButton
                        type="primary"
                        icon={
                          <Eye size={16} />
                        }
                        onClick={() => handlePreview(selectedNode)}
                      >
                        {t('tenant.instances.files.preview')}
                      </AntButton>
                      <AntButton
                        icon={
                          <Download size={16} />
                        }
                        onClick={() => handleDownload(selectedNode)}
                      >
                        {t('common.download')}
                      </AntButton>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="flex flex-col items-center justify-center py-20 text-slate-500 dark:text-slate-400">
                <FolderOpen size={16} className="text-5xl mb-3" />
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
            <pre className="bg-slate-100 dark:bg-slate-900 p-4 rounded-lg text-sm overflow-x-auto font-mono">
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
        onOk={handleCreate}
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
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('tenant.instances.files.parentFolder')}
              </label>
              <Input value={createParentPath} disabled />
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {createType === 'folder'
                ? t('tenant.instances.files.folderName')
                : t('tenant.instances.files.fileName')}
            </label>
            <Input
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
