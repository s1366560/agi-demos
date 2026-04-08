import { useCallback, useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';

import {
  ChevronRight,
  Download,
  FileCode,
  FileText,
  Folder,
  FolderPlus,
  Image,
  Loader2,
  Trash2,
  Upload,
  X,
} from 'lucide-react';

import { blackboardFileService } from '@/services/blackboardFileService';

import type { BlackboardFileItem } from '@/services/blackboardFileService';

export interface SharedFileBrowserProps {
  tenantId: string;
  projectId: string;
  workspaceId: string;
}

function isTextType(contentType: string): boolean {
  return (
    contentType.startsWith('text/') ||
    [
      'application/json',
      'application/javascript',
      'application/xml',
      'application/yaml',
      'application/x-yaml',
    ].includes(contentType)
  );
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileIcon(item: BlackboardFileItem) {
  if (item.is_directory) return <Folder className="h-4 w-4 text-primary" />;
  if (item.content_type.startsWith('image/')) return <Image className="h-4 w-4 text-warning" />;
  if (
    item.content_type.includes('javascript') ||
    item.content_type.includes('json') ||
    item.content_type.includes('python')
  )
    return <FileCode className="h-4 w-4 text-success" />;
  return <FileText className="h-4 w-4 text-text-secondary dark:text-text-muted" />;
}

export function SharedFileBrowser({ tenantId, projectId, workspaceId }: SharedFileBrowserProps) {
  const { t } = useTranslation();
  const [currentPath, setCurrentPath] = useState('/');
  const [files, setFiles] = useState<BlackboardFileItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [showMkdir, setShowMkdir] = useState(false);
  const [newDirName, setNewDirName] = useState('');
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [previewFile, setPreviewFile] = useState<BlackboardFileItem | null>(null);
  const [previewContent, setPreviewContent] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);

  const fetchFiles = useCallback(async () => {
    setLoading(true);
    try {
      const items = await blackboardFileService.listFiles(
        tenantId,
        projectId,
        workspaceId,
        currentPath,
      );
      setFiles(items);
    } catch (err) {
      console.error('Failed to fetch files:', err);
    } finally {
      setLoading(false);
    }
  }, [tenantId, projectId, workspaceId, currentPath]);

  useEffect(() => {
    void fetchFiles();
  }, [fetchFiles]);

  const breadcrumbs = (() => {
    const parts = currentPath.split('/').filter(Boolean);
    const crumbs = [{ name: '/', path: '/' }];
    let acc = '/';
    for (const p of parts) {
      acc += p + '/';
      crumbs.push({ name: p, path: acc });
    }
    return crumbs;
  })();

  const navigateToDir = (item: BlackboardFileItem) => {
    if (item.is_directory) {
      setCurrentPath(currentPath + item.name + '/');
    }
  };

  const navigateTo = (path: string) => {
    setCurrentPath(path);
  };

  const handleMkdir = async () => {
    if (!newDirName.trim()) return;
    setCreating(true);
    try {
      await blackboardFileService.createDirectory(
        tenantId,
        projectId,
        workspaceId,
        currentPath,
        newDirName.trim(),
      );
      setNewDirName('');
      setShowMkdir(false);
      await fetchFiles();
    } catch (err) {
      console.error('Failed to create directory:', err);
    } finally {
      setCreating(false);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await blackboardFileService.uploadFile(tenantId, projectId, workspaceId, currentPath, file);
      await fetchFiles();
    } catch (err) {
      console.error('Failed to upload file:', err);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDownload = async (item: BlackboardFileItem) => {
    try {
      const blob = await blackboardFileService.downloadFile(
        tenantId,
        projectId,
        workspaceId,
        item.id,
      );
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = item.name;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to download:', err);
    }
  };

  const handleDelete = async (item: BlackboardFileItem) => {
    setDeletingId(item.id);
    try {
      await blackboardFileService.deleteFile(tenantId, projectId, workspaceId, item.id);
      await fetchFiles();
    } catch (err) {
      console.error('Failed to delete:', err);
    } finally {
      setDeletingId(null);
    }
  };

  const openPreview = async (item: BlackboardFileItem) => {
    if (item.is_directory) return;
    setPreviewFile(item);
    setPreviewLoading(true);
    setPreviewContent(null);
    try {
      const blob = await blackboardFileService.downloadFile(
        tenantId,
        projectId,
        workspaceId,
        item.id,
      );
      if (item.content_type.startsWith('image/') || item.content_type === 'application/pdf') {
        setPreviewContent(URL.createObjectURL(blob));
      } else if (isTextType(item.content_type)) {
        setPreviewContent(await blob.text());
      }
    } catch (err) {
      console.error('Failed to load preview:', err);
    } finally {
      setPreviewLoading(false);
    }
  };

  const closePreview = () => {
    if (
      previewContent &&
      (previewFile?.content_type.startsWith('image/') ||
        previewFile?.content_type === 'application/pdf')
    ) {
      URL.revokeObjectURL(previewContent);
    }
    setPreviewFile(null);
    setPreviewContent(null);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.currentTarget === e.target) {
      setIsDragOver(false);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    const droppedFiles = Array.from(e.dataTransfer.files);
    if (droppedFiles.length === 0) return;
    setUploading(true);
    try {
      for (const file of droppedFiles) {
        await blackboardFileService.uploadFile(
          tenantId,
          projectId,
          workspaceId,
          currentPath,
          file,
        );
      }
      await fetchFiles();
    } catch (err) {
      console.error('Failed to upload dropped files:', err);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      className="relative space-y-4"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={(e) => void handleDrop(e)}
    >
      {/* Breadcrumb */}
      <div className="flex items-center gap-1 text-sm text-text-secondary dark:text-text-muted">
        {breadcrumbs.map((crumb, i) => (
          <span key={crumb.path} className="flex items-center gap-1">
            {i > 0 && <ChevronRight className="h-3 w-3" />}
            <button
              type="button"
              onClick={() => navigateTo(crumb.path)}
              className={`rounded px-1.5 py-0.5 transition hover:bg-surface-muted dark:hover:bg-surface-elevated ${
                i === breadcrumbs.length - 1
                  ? 'font-medium text-text-primary dark:text-text-inverse'
                  : ''
              }`}
            >
              {crumb.name}
            </button>
          </span>
        ))}
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setShowMkdir(true)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-sm text-text-secondary transition hover:bg-surface-muted dark:border-border-dark dark:text-text-muted dark:hover:bg-surface-elevated"
        >
          <FolderPlus className="h-4 w-4" />
          {t('blackboard.files.newFolder', 'New Folder')}
        </button>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-sm text-text-secondary transition hover:bg-surface-muted disabled:opacity-50 dark:border-border-dark dark:text-text-muted dark:hover:bg-surface-elevated"
        >
          {uploading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Upload className="h-4 w-4" />
          )}
          {t('blackboard.files.upload', 'Upload')}
        </button>
        <input ref={fileInputRef} type="file" className="hidden" onChange={handleUpload} />
      </div>

      {/* Mkdir inline */}
      {showMkdir && (
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={newDirName}
            onChange={(e) => setNewDirName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void handleMkdir();
              if (e.key === 'Escape') setShowMkdir(false);
            }}
            placeholder={t('blackboard.files.folderName', 'Folder name')}
            autoFocus
            className="rounded-md border border-border-light bg-surface-light px-3 py-1.5 text-sm text-text-primary outline-none focus:ring-1 focus:ring-primary dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse"
          />
          <button
            type="button"
            onClick={() => void handleMkdir()}
            disabled={creating || !newDirName.trim()}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-white transition hover:bg-primary/90 disabled:opacity-50"
          >
            {creating ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              t('blackboard.files.create', 'Create')
            )}
          </button>
          <button
            type="button"
            onClick={() => {
              setShowMkdir(false);
              setNewDirName('');
            }}
            className="rounded-md px-2 py-1.5 text-sm text-text-secondary hover:text-text-primary dark:text-text-muted dark:hover:text-text-inverse"
          >
            {t('common.cancel', 'Cancel')}
          </button>
        </div>
      )}

      {/* File list */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-text-secondary dark:text-text-muted" />
        </div>
      ) : files.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border-separator bg-surface-light p-8 text-center dark:border-border-dark dark:bg-surface-dark">
          <div className="text-sm text-text-secondary dark:text-text-muted">
            {t(
              'blackboard.files.empty',
              'No files yet. Upload a file or create a folder to get started.',
            )}
          </div>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border-light dark:border-border-dark">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light bg-surface-muted/50 dark:border-border-dark dark:bg-surface-elevated/50">
                <th className="px-4 py-2.5 text-left font-medium text-text-secondary dark:text-text-muted">
                  {t('blackboard.files.name', 'Name')}
                </th>
                <th className="hidden px-4 py-2.5 text-left font-medium text-text-secondary dark:text-text-muted sm:table-cell">
                  {t('blackboard.files.size', 'Size')}
                </th>
                <th className="hidden px-4 py-2.5 text-left font-medium text-text-secondary dark:text-text-muted md:table-cell">
                  {t('blackboard.files.uploader', 'Uploader')}
                </th>
                <th className="px-4 py-2.5 text-right font-medium text-text-secondary dark:text-text-muted">
                  {t('blackboard.files.actions', 'Actions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {files.map((item) => (
                <tr
                  key={item.id}
                  className="border-b border-border-light last:border-b-0 transition hover:bg-surface-muted/30 dark:border-border-dark dark:hover:bg-surface-elevated/30"
                >
                  <td className="px-4 py-2.5">
                    <button
                      type="button"
                      onClick={() =>
                        item.is_directory ? navigateToDir(item) : void openPreview(item)
                      }
                      className="flex items-center gap-2 text-text-primary dark:text-text-inverse"
                    >
                      {fileIcon(item)}
                      <span
                        className={
                          item.is_directory
                            ? 'font-medium hover:underline'
                            : 'hover:text-primary hover:underline'
                        }
                      >
                        {item.name}
                      </span>
                    </button>
                  </td>
                  <td className="hidden px-4 py-2.5 text-text-secondary dark:text-text-muted sm:table-cell">
                    {formatFileSize(item.file_size)}
                  </td>
                  <td className="hidden px-4 py-2.5 text-text-secondary dark:text-text-muted md:table-cell">
                    {item.uploader_name}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end gap-1">
                      {!item.is_directory && (
                        <button
                          type="button"
                          onClick={() => void handleDownload(item)}
                          className="rounded p-1.5 text-text-secondary transition hover:bg-surface-muted hover:text-text-primary dark:text-text-muted dark:hover:bg-surface-elevated dark:hover:text-text-inverse"
                          title={t('blackboard.files.download', 'Download')}
                        >
                          <Download className="h-4 w-4" />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => void handleDelete(item)}
                        disabled={deletingId === item.id}
                        className="rounded p-1.5 text-text-secondary transition hover:bg-error/10 hover:text-error dark:text-text-muted"
                        title={t('blackboard.files.delete', 'Delete')}
                      >
                        {deletingId === item.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Drag overlay */}
      {isDragOver && (
        <div className="pointer-events-none absolute inset-0 z-40 flex items-center justify-center rounded-xl border-2 border-dashed border-primary bg-primary/5">
          <div className="flex flex-col items-center gap-2">
            <Upload className="h-10 w-10 text-primary" />
            <span className="text-sm font-medium text-primary">
              {t('blackboard.files.dropToUpload', 'Drop files to upload')}
            </span>
          </div>
        </div>
      )}

      {/* File preview modal */}
      {previewFile && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="relative mx-4 max-h-[85vh] w-full max-w-4xl overflow-hidden rounded-xl border border-border-light bg-surface-light shadow-2xl dark:border-border-dark dark:bg-surface-dark">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-border-light px-5 py-3 dark:border-border-dark">
              <div className="flex items-center gap-2">
                {fileIcon(previewFile)}
                <span className="font-medium text-text-primary dark:text-text-inverse">
                  {previewFile.name}
                </span>
                <span className="text-xs text-text-secondary dark:text-text-muted">
                  {formatFileSize(previewFile.file_size)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void handleDownload(previewFile)}
                  className="rounded-lg px-3 py-1.5 text-sm text-text-secondary hover:bg-surface-muted dark:text-text-muted dark:hover:bg-surface-elevated"
                >
                  {t('blackboard.files.download', 'Download')}
                </button>
                <button
                  type="button"
                  onClick={closePreview}
                  className="rounded-lg p-1.5 text-text-secondary hover:bg-surface-muted dark:text-text-muted dark:hover:bg-surface-elevated"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            </div>
            {/* Content */}
            <div className="max-h-[calc(85vh-56px)] overflow-auto p-5">
              {previewLoading ? (
                <div className="flex items-center justify-center py-20">
                  <Loader2 className="h-8 w-8 animate-spin text-text-secondary dark:text-text-muted" />
                </div>
              ) : previewFile.content_type.startsWith('image/') ? (
                <img
                  src={previewContent || ''}
                  alt={previewFile.name}
                  className="mx-auto max-h-[70vh] rounded-lg object-contain"
                />
              ) : previewFile.content_type === 'application/pdf' ? (
                <iframe
                  src={previewContent || ''}
                  className="h-[70vh] w-full rounded-lg border-0"
                  title={previewFile.name}
                />
              ) : isTextType(previewFile.content_type) ? (
                <pre className="whitespace-pre-wrap rounded-lg bg-surface-muted p-4 font-mono text-sm text-text-primary dark:bg-surface-dark-alt dark:text-text-inverse">
                  {previewContent}
                </pre>
              ) : (
                <div className="py-12 text-center">
                  <p className="text-text-secondary dark:text-text-muted">
                    {t(
                      'blackboard.files.noPreview',
                      'Preview not available for this file type.',
                    )}
                  </p>
                  <button
                    type="button"
                    onClick={() => void handleDownload(previewFile)}
                    className="mt-4 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90"
                  >
                    {t('blackboard.files.download', 'Download')}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
