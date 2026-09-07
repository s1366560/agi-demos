import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useI18n } from '../../i18n';
import type { ComposerContextItem } from '../../types';
import type { ComposerCatalogClient } from './composerCatalogModel';
import { uploadComposerFilesSequentially } from './composerFileDropModel';

type UseComposerFileUploadOptions = {
  api: ComposerCatalogClient;
  contextKey?: string;
  onAdd: (item: ComposerContextItem) => void;
};

export function useComposerFileUpload({ api, onAdd, contextKey }: UseComposerFileUploadOptions) {
  const { t } = useI18n();
  const [uploadingFileCount, setUploadingFileCount] = useState(0);
  const [fileUploadErrors, setFileUploadErrors] = useState<string[]>([]);

  const lifetime = useMemo(() => ({ active: true }), [api, contextKey]);
  const currentLifetime = useRef(lifetime);
  currentLifetime.current = lifetime;
  const batchRef = useRef<AbortController | null>(null);
  useEffect(() => {
    lifetime.active = true;
    setUploadingFileCount(0);
    setFileUploadErrors([]);
    return () => {
      lifetime.active = false;
      batchRef.current?.abort();
      batchRef.current = null;
    };
  }, [lifetime]);
  const isActive = useCallback(
    () => lifetime.active && currentLifetime.current === lifetime,
    [lifetime],
  );
  const uploadFiles = useCallback(
    async (files: File[]) => {
      if (!files.length || !isActive()) return;
      const uploadFile = api.uploadSandboxFile?.bind(api);
      if (!uploadFile) {
        setFileUploadErrors([t('composer.fileUploadUnavailable')]);
        return;
      }
      batchRef.current?.abort();
      const controller = new AbortController();
      batchRef.current = controller;
      const current = () =>
        isActive() && !controller.signal.aborted && batchRef.current === controller;
      setFileUploadErrors([]);
      setUploadingFileCount(files.length);
      try {
        const result = await uploadComposerFilesSequentially(
          files,
          uploadFile,
          (count) => {
            if (current()) setUploadingFileCount(count);
          },
          controller.signal,
        );
        if (!current()) return;
        for (const { metadata } of result.uploaded) {
          if (!current()) return;
          onAdd({
            kind: 'attachment',
            resource_id: metadata.sandbox_path,
            label: metadata.filename,
            metadata: { ...metadata },
          });
        }
        if (!current()) return;
        setFileUploadErrors(
          result.failures.map((failure) =>
            t('composer.fileUploadFailed', {
              filename: failure.filename,
              error:
                failure.reason === 'too_large'
                  ? t('composer.fileTooLarge')
                  : (failure.error ?? t('composer.fileUploadUnavailable')),
            }),
          ),
        );
      } catch (error) {
        if (current())
          setFileUploadErrors([error instanceof Error ? error.message : String(error)]);
      } finally {
        if (current()) {
          setUploadingFileCount(0);
          batchRef.current = null;
        }
      }
    },
    [api, isActive, onAdd, t],
  );
  const rejectFileDrop = useCallback(() => {
    if (isActive()) setFileUploadErrors([t('composer.fileDropUnsupported')]);
  }, [isActive, t]);

  return {
    supportsFileUpload: Boolean(api.uploadSandboxFile),
    uploadingFileCount,
    uploadingAttachments: uploadingFileCount > 0,
    fileUploadErrors,
    uploadFiles,
    rejectFileDrop,
  };
}
