import { useCallback, useState } from 'react';

import { useI18n } from '../../i18n';
import type { ComposerContextItem } from '../../types';
import type { ComposerCatalogClient } from './composerCatalogModel';
import { uploadComposerFilesSequentially } from './composerFileDropModel';

type UseComposerFileUploadOptions = {
  api: ComposerCatalogClient;
  onAdd: (item: ComposerContextItem) => void;
};

export function useComposerFileUpload({ api, onAdd }: UseComposerFileUploadOptions) {
  const { t } = useI18n();
  const [uploadingFileCount, setUploadingFileCount] = useState(0);
  const [fileUploadErrors, setFileUploadErrors] = useState<string[]>([]);

  const uploadFiles = useCallback(
    async (files: File[]) => {
      if (!files.length) return;
      const uploadFile = api.uploadSandboxFile?.bind(api);
      if (!uploadFile) {
        setFileUploadErrors([t('composer.fileUploadUnavailable')]);
        return;
      }

      setFileUploadErrors([]);
      setUploadingFileCount(files.length);
      const result = await uploadComposerFilesSequentially(
        files,
        uploadFile,
        setUploadingFileCount,
      );
      for (const { metadata } of result.uploaded) {
        onAdd({
          kind: 'attachment',
          resource_id: metadata.sandbox_path,
          label: metadata.filename,
          metadata: { ...metadata },
        });
      }
      setFileUploadErrors(
        result.failures.map((failure) =>
          failure.reason === 'too_large'
            ? t('composer.fileUploadFailed', {
                filename: failure.filename,
                error: t('composer.fileTooLarge'),
              })
            : t('composer.fileUploadFailed', {
                filename: failure.filename,
                error: failure.error ?? t('composer.fileUploadUnavailable'),
              }),
        ),
      );
    },
    [api, onAdd, t],
  );

  const rejectFileDrop = useCallback(() => {
    setFileUploadErrors([t('composer.fileDropUnsupported')]);
  }, [t]);

  return {
    supportsFileUpload: Boolean(api.uploadSandboxFile),
    uploadingFileCount,
    uploadingAttachments: uploadingFileCount > 0,
    fileUploadErrors,
    uploadFiles,
    rejectFileDrop,
  };
}
