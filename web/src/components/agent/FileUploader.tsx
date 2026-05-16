/**
 * FileUploader - Upload hook and types for sandbox file uploads
 *
 * Exports:
 * - useFileUpload: Hook managing file upload state and sandbox upload logic
 * - PendingAttachment: Type for tracking upload state per file
 */

import { useState, useCallback, useRef } from 'react';

import { useTranslation } from 'react-i18next';

import { sandboxUploadService, type FileMetadata } from '@/services/sandboxUploadService';

import { message } from '@/components/ui/lazyAntd';

// ==================== Types ====================

export interface PendingAttachment {
  id: string;
  file: File;
  filename: string;
  mimeType: string;
  sizeBytes: number;
  status: 'pending' | 'uploading' | 'uploaded' | 'error';
  progress: number;
  error?: string | undefined;
  fileMetadata?: FileMetadata | undefined;
}

// ==================== Hook ====================

interface UseFileUploadOptions {
  projectId?: string | undefined;
  maxFiles?: number | undefined;
  maxSizeMB?: number | undefined;
}

export function useFileUpload({ projectId, maxFiles = 10, maxSizeMB = 100 }: UseFileUploadOptions) {
  const { t } = useTranslation();
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const idCounter = useRef(0);

  const generateId = useCallback(() => {
    idCounter.current += 1;
    return `file-${String(Date.now())}-${String(idCounter.current)}`;
  }, []);

  const uploadSingleFile = useCallback(
    async (file: File, tempId: string) => {
      if (!projectId) {
        const errorMsg = t('components.fileUpload.messages.missingProject');
        message.error(errorMsg);
        setAttachments((prev) =>
          prev.map((a) =>
            a.id === tempId ? { ...a, status: 'error' as const, error: errorMsg } : a
          )
        );
        return;
      }

      try {
        const result = await sandboxUploadService.upload(projectId, file, (progress) => {
          setAttachments((prev) =>
            prev.map((a) => (a.id === tempId ? { ...a, progress: progress.percentage } : a))
          );
        });

        if (result.success) {
          const fileMetadata: FileMetadata = {
            filename: file.name,
            sandbox_path: result.sandbox_path,
            mime_type: file.type || 'application/octet-stream',
            size_bytes: result.size_bytes,
          };
          setAttachments((prev) =>
            prev.map((a) =>
              a.id === tempId
                ? { ...a, status: 'uploaded' as const, progress: 100, fileMetadata }
                : a
            )
          );
        } else {
          throw new Error(result.error || t('components.fileUpload.errors.sandboxFailed'));
        }
      } catch (error) {
        const errorMsg =
          error instanceof Error ? error.message : t('components.fileUpload.errors.uploadFailed');
        message.error(
          t('components.fileUpload.messages.uploadFailed', { name: file.name, errorMsg })
        );
        setAttachments((prev) =>
          prev.map((a) =>
            a.id === tempId ? { ...a, status: 'error' as const, error: errorMsg } : a
          )
        );
      }
    },
    [projectId, t]
  );

  const addFiles = useCallback(
    (fileList: FileList) => {
      if (!projectId) {
        message.error(t('components.fileUpload.messages.missingProject'));
        return;
      }

      const files = Array.from(fileList);

      setAttachments((prev) => {
        const available = maxFiles - prev.length;
        if (available <= 0) {
          message.warning(t('components.fileUpload.messages.maxFiles', { count: maxFiles }));
          return prev;
        }

        const toAdd = files.slice(0, available);
        if (toAdd.length < files.length) {
          message.warning(t('components.fileUpload.messages.remainingFiles', { count: available }));
        }

        const newAttachments: PendingAttachment[] = [];
        for (const file of toAdd) {
          if (file.size > maxSizeMB * 1024 * 1024) {
            message.error(
              t('components.fileUpload.messages.sizeLimit', { name: file.name, maxSizeMB })
            );
            continue;
          }
          const id = generateId();
          newAttachments.push({
            id,
            file,
            filename: file.name,
            mimeType: file.type || 'application/octet-stream',
            sizeBytes: file.size,
            status: 'uploading',
            progress: 0,
          });
          // Fire upload (runs concurrently, updates state via setAttachments)
          void uploadSingleFile(file, id);
        }

        return [...prev, ...newAttachments];
      });
    },
    [maxFiles, maxSizeMB, projectId, generateId, uploadSingleFile, t]
  );

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const retryAttachment = useCallback(
    (id: string) => {
      setAttachments((prev) => {
        const target = prev.find((a) => a.id === id);
        if (!target || target.status !== 'error') return prev;

        const newId = generateId();
        void uploadSingleFile(target.file, newId);

        return prev.map((a) =>
          a.id === id
            ? { ...a, id: newId, status: 'uploading' as const, progress: 0, error: undefined }
            : a
        );
      });
    },
    [generateId, uploadSingleFile]
  );

  const clearAll = useCallback(() => {
    setAttachments([]);
  }, []);

  return { attachments, addFiles, removeAttachment, retryAttachment, clearAll };
}
