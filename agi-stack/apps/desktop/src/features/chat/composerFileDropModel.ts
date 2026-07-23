import type { AgentInputFileMetadata } from '../../types';

export const MAX_COMPOSER_ATTACHMENT_BYTES = 100 * 1024 * 1024;

export type ComposerUploadFile = Pick<File, 'name' | 'type' | 'size' | 'arrayBuffer'>;

export type ComposerFileUploadFailure = {
  filename: string;
  reason: 'too_large' | 'upload_failed';
  error?: string;
};

export type ComposerFileUploadBatchResult = {
  uploaded: Array<{
    file: ComposerUploadFile;
    metadata: AgentInputFileMetadata;
  }>;
  failures: ComposerFileUploadFailure[];
};

export function composerFileDragActive({
  disabled,
  supportsUpload,
  types,
}: {
  disabled: boolean;
  supportsUpload: boolean;
  types: readonly string[];
}): boolean {
  return !disabled && supportsUpload && types.includes('Files');
}

export function composerFileDropAction({
  disabled,
  supportsUpload,
  fileCount,
}: {
  disabled: boolean;
  supportsUpload: boolean;
  fileCount: number;
}): 'upload' | 'unsupported' | 'ignore' {
  if (disabled || fileCount <= 0) return 'ignore';
  return supportsUpload ? 'upload' : 'unsupported';
}

export async function uploadComposerFilesSequentially(
  files: readonly ComposerUploadFile[],
  uploadFile: (file: ComposerUploadFile) => Promise<AgentInputFileMetadata>,
  onRemainingChange?: (count: number) => void,
): Promise<ComposerFileUploadBatchResult> {
  const uploaded: ComposerFileUploadBatchResult['uploaded'] = [];
  const failures: ComposerFileUploadFailure[] = [];

  for (const [index, file] of files.entries()) {
    try {
      if (file.size > MAX_COMPOSER_ATTACHMENT_BYTES) {
        failures.push({ filename: file.name, reason: 'too_large' });
        continue;
      }
      uploaded.push({ file, metadata: await uploadFile(file) });
    } catch (caught) {
      failures.push({
        filename: file.name,
        reason: 'upload_failed',
        error: caught instanceof Error ? caught.message : String(caught),
      });
    } finally {
      onRemainingChange?.(files.length - index - 1);
    }
  }

  return { uploaded, failures };
}
