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
  RefreshCw,
  Trash2,
  Upload,
  X,
} from 'lucide-react';

import { blackboardFileService } from '@/services/blackboardFileService';
import type { BlackboardFileItem } from '@/services/blackboardFileService';
import { parseError } from '@/services/client/ApiError';

import { useLazyMessage } from '@/components/ui/lazyAntd';

import { OwnedSurfaceBadge } from '../OwnedSurfaceBadge';

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
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getErrorMessage(error: unknown, fallback: string): string {
  const parsed = parseError(error);
  return parsed.message || fallback;
}

function isValidDirectoryName(name: string): boolean {
  const trimmed = name.trim();
  return (
    Boolean(trimmed) &&
    !trimmed.includes('/') &&
    !trimmed.includes('\\') &&
    trimmed !== '.' &&
    trimmed !== '..'
  );
}

function buildChildPath(parentPath: string, childName: string): string {
  const normalizedParent = parentPath.endsWith('/') ? parentPath : `${parentPath}/`;
  return `${normalizedParent}${childName}/`;
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
  const message = useLazyMessage();
  const [currentPath, setCurrentPath] = useState('/');
  const [files, setFiles] = useState<BlackboardFileItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
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
        currentPath
      );
      setFiles(items);
      setErrorMessage(null);
    } catch (err) {
      setErrorMessage(
        getErrorMessage(err, t('blackboard.files.errors.load', 'Failed to load files'))
      );
    } finally {
      setLoading(false);
    }
  }, [tenantId, projectId, workspaceId, currentPath, t]);

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
      setCurrentPath(buildChildPath(currentPath, item.name));
    }
  };

  const navigateTo = (path: string) => {
    setCurrentPath(path);
  };

  const handleMkdir = async () => {
    if (!isValidDirectoryName(newDirName)) {
      const errorText = t(
        'blackboard.files.errors.invalidFolder',
        'Folder name cannot contain slashes.'
      );
      setErrorMessage(errorText);
      void message?.error(errorText);
      return;
    }
    setCreating(true);
    try {
      await blackboardFileService.createDirectory(
        tenantId,
        projectId,
        workspaceId,
        currentPath,
        newDirName.trim()
      );
      setNewDirName('');
      setShowMkdir(false);
      setErrorMessage(null);
      void message?.success(t('blackboard.files.folderCreated', 'Folder created'));
      await fetchFiles();
    } catch (err) {
      const errorText = getErrorMessage(
        err,
        t('blackboard.files.errors.createFolder', 'Failed to create folder')
      );
      setErrorMessage(errorText);
      void message?.error(errorText);
    } finally {
      setCreating(false);
    }
  };

  const uploadFiles = async (selectedFiles: File[]) => {
    if (selectedFiles.length === 0) return;
    setUploading(true);
    try {
      for (const file of selectedFiles) {
        await blackboardFileService.uploadFile(tenantId, projectId, workspaceId, currentPath, file);
      }
      setErrorMessage(null);
      void message?.success(
        t('blackboard.files.uploaded', 'Uploaded {{count}} file(s)', {
          count: selectedFiles.length,
        })
      );
      await fetchFiles();
    } catch (err) {
      const errorText = getErrorMessage(
        err,
        t('blackboard.files.errors.upload', 'Failed to upload file')
      );
      setErrorMessage(errorText);
      void message?.error(errorText);
    } finally {
      setUploading(false);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(e.target.files ?? []);
    try {
      await uploadFiles(selectedFiles);
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDownload = async (item: BlackboardFileItem) => {
    try {
      const blob = await blackboardFileService.downloadFile(
        tenantId,
        projectId,
        workspaceId,
        item.id
      );
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = item.name;
      a.click();
      window.setTimeout(() => {
        URL.revokeObjectURL(url);
      }, 0);
    } catch (err) {
      const errorText = getErrorMessage(
        err,
        t('blackboard.files.errors.download', 'Failed to download file')
      );
      setErrorMessage(errorText);
      void message?.error(errorText);
    }
  };

  const handleDelete = async (item: BlackboardFileItem) => {
    const confirmed = window.confirm(
      t('blackboard.files.deleteConfirm', 'Delete {{name}}?', { name: item.name })
    );
    if (!confirmed) return;
    setDeletingId(item.id);
    try {
      await blackboardFileService.deleteFile(tenantId, projectId, workspaceId, item.id);
      setErrorMessage(null);
      void message?.success(t('blackboard.files.deleted', 'Deleted {{name}}', { name: item.name }));
      await fetchFiles();
    } catch (err) {
      const errorText = getErrorMessage(
        err,
        t('blackboard.files.errors.delete', 'Failed to delete file')
      );
      setErrorMessage(errorText);
      void message?.error(errorText);
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
        item.id
      );
      if (item.content_type.startsWith('image/') || item.content_type === 'application/pdf') {
        setPreviewContent(URL.createObjectURL(blob));
      } else if (isTextType(item.content_type)) {
        setPreviewContent(await blob.text());
      }
    } catch (err) {
      const errorText = getErrorMessage(
        err,
        t('blackboard.files.errors.preview', 'Failed to load preview')
      );
      setErrorMessage(errorText);
      void message?.error(errorText);
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
    await uploadFiles(droppedFiles);
  };

  return (
    <div
      className="relative space-y-4"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={(e) => void handleDrop(e)}
    >
      <OwnedSurfaceBadge
        labelKey="blackboard.filesSurfaceHint"
        fallbackLabel="blackboard file workspace"
      />

      {errorMessage && (
        <div
          role="alert"
          className="flex flex-col gap-3 rounded-md border border-error/25 bg-error/10 px-3 py-2 text-sm text-status-text-error dark:text-status-text-error-dark sm:flex-row sm:items-center sm:justify-between"
        >
          <span className="break-words">{errorMessage}</span>
          <button
            type="button"
            onClick={() => void fetchFiles()}
            disabled={loading}
            className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-md border border-error/25 bg-surface-light px-3 text-sm font-medium transition hover:bg-error/15 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white/5"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            {t('common.retry', 'Retry')}
          </button>
        </div>
      )}

      {/* Breadcrumb */}
      <div className="flex items-center gap-1 text-sm text-text-secondary dark:text-text-muted">
        {breadcrumbs.map((crumb, i) => (
          <span key={crumb.path} className="flex items-center gap-1">
            {i > 0 && <ChevronRight className="h-3 w-3" />}
            <button
              type="button"
              onClick={() => {
                navigateTo(crumb.path);
              }}
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
          onClick={() => {
            setShowMkdir(true);
          }}
          aria-label={t('blackboard.files.newFolder', 'New Folder')}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-sm text-text-secondary transition hover:bg-surface-muted dark:border-border-dark dark:text-text-muted dark:hover:bg-surface-elevated"
        >
          <FolderPlus className="h-4 w-4" />
          {t('blackboard.files.newFolder', 'New Folder')}
        </button>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          aria-label={t('blackboard.files.upload', 'Upload')}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-sm text-text-secondary transition hover:bg-surface-muted disabled:opacity-50 dark:border-border-dark dark:text-text-muted dark:hover:bg-surface-elevated"
        >
          {uploading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Upload className="h-4 w-4" />
          )}
          {t('blackboard.files.upload', 'Upload')}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(event) => {
            void handleUpload(event);
          }}
        />
      </div>

      {/* Mkdir inline */}
      {showMkdir && (
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={newDirName}
            onChange={(e) => {
              setNewDirName(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void handleMkdir();
              if (e.key === 'Escape') setShowMkdir(false);
            }}
            placeholder={t('blackboard.files.folderName', 'Folder name')}
            autoFocus
            aria-label={t('blackboard.files.folderName', 'Folder name')}
            className="rounded-md border border-border-light bg-surface-light px-3 py-1.5 text-sm text-text-primary outline-none focus:ring-1 focus:ring-primary dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse"
          />
          <button
            type="button"
            onClick={() => void handleMkdir()}
            disabled={creating || !isValidDirectoryName(newDirName)}
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
              'No files yet. Upload a file or create a folder to get started.'
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
                      onClick={() => {
                        if (item.is_directory) {
                          navigateToDir(item);
                        } else {
                          void openPreview(item);
                        }
                      }}
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
                          aria-label={t('blackboard.files.downloadNamed', 'Download {{name}}', {
                            name: item.name,
                          })}
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
                        aria-label={t('blackboard.files.deleteNamed', 'Delete {{name}}', {
                          name: item.name,
                        })}
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
                  aria-label={t('blackboard.files.downloadNamed', 'Download {{name}}', {
                    name: previewFile.name,
                  })}
                  className="rounded-lg px-3 py-1.5 text-sm text-text-secondary hover:bg-surface-muted dark:text-text-muted dark:hover:bg-surface-elevated"
                >
                  {t('blackboard.files.download', 'Download')}
                </button>
                <button
                  type="button"
                  onClick={closePreview}
                  aria-label={t('common.close', 'Close')}
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
                    {t('blackboard.files.noPreview', 'Preview not available for this file type.')}
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
