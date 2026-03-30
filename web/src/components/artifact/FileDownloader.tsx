/**
 * FileDownloader - Download button for non-previewable files
 */

import React from 'react';

import { Button, Space, Typography, Card } from 'antd';
import {
  Download,
  File,
  FileArchive,
  FileText,
  FileSpreadsheet,
} from 'lucide-react';

const { Text } = Typography;

export interface FileDownloaderProps {
  /** Download URL */
  url: string;
  /** Filename */
  filename: string;
  /** MIME type */
  mimeType?: string | undefined;
  /** File size in bytes */
  sizeBytes?: number | undefined;
  /** Compact mode */
  compact?: boolean | undefined;
}

// Format file size
function formatFileSize(bytes?: number): string {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

// Get icon based on mime type
function getFileIcon(mimeType?: string, filename?: string): React.ReactNode {
  if (!mimeType && !filename) return <File size={36} />;

  // Check extension
  const ext = filename?.split('.').pop()?.toLowerCase();

  if (
    mimeType?.includes('zip') ||
    mimeType?.includes('tar') ||
    mimeType?.includes('gzip') ||
    ext === 'zip' ||
    ext === 'tar' ||
    ext === 'gz' ||
    ext === 'rar' ||
    ext === '7z'
  ) {
    return <FileArchive size={36} />;
  }

  if (mimeType?.includes('pdf') || ext === 'pdf') {
    return <FileText size={36} />;
  }

  if (mimeType?.includes('word') || ext === 'doc' || ext === 'docx') {
    return <FileText size={36} />;
  }

  if (
    mimeType?.includes('excel') ||
    mimeType?.includes('spreadsheet') ||
    ext === 'xls' ||
    ext === 'xlsx' ||
    ext === 'csv'
  ) {
    return <FileSpreadsheet size={36} />;
  }

  return <File size={36} />;
}

export const FileDownloader: React.FC<FileDownloaderProps> = ({
  url,
  filename,
  mimeType,
  sizeBytes,
  compact = false,
}) => {
  const icon = getFileIcon(mimeType, filename);
  const size = formatFileSize(sizeBytes);

  if (compact) {
    return (
      <Button
        type="primary"
        icon={<Download size={14} />}
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        size="small"
      >
        {filename}
      </Button>
    );
  }

  return (
    <Card className="file-downloader" size="small">
      <Space direction="vertical" align="center" className="w-full py-4">
        <div className="text-gray-400">{icon}</div>
        <Text ellipsis style={{ maxWidth: 200 }}>
          {filename}
        </Text>
        {size && (
          <Text type="secondary" className="text-xs">
            {size}
          </Text>
        )}
        <Button
          type="primary"
          icon={<Download size={16} />}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Download
        </Button>
      </Space>
    </Card>
  );
};

export default FileDownloader;
