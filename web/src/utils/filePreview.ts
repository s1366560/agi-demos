/** Office MIME types that our canvas can preview */
const OFFICE_MIME_TYPES = [
  'application/msword',
  'application/vnd.ms-excel',
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
];

/** Check if MIME type is an Office document */
export const isOfficeMimeType = (mime: string): boolean =>
  OFFICE_MIME_TYPES.includes(mime);

/** Check if filename has an Office extension */
export const isOfficeExtension = (filename: string): boolean => {
  const ext = filename.split('.').pop()?.toLowerCase();
  return ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'].includes(ext || '');
};

/**
 * Check if a file (by MIME type and optional filename) can be previewed
 * in the canvas panel. This covers: images, video, audio, PDF, and Office docs.
 */
export const isCanvasPreviewable = (mimeType: string, filename?: string): boolean => {
  const mime = mimeType.toLowerCase();
  return (
    mime === 'application/pdf' ||
    mime.startsWith('image/') ||
    mime.startsWith('video/') ||
    mime.startsWith('audio/') ||
    isOfficeMimeType(mime) ||
    (filename ? isOfficeExtension(filename) : false)
  );
};
