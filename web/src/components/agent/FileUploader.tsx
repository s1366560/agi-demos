/**
 * FileUploader - File attachment component for agent chat
 * 
 * Features:
 * - File selection (click or drag-drop)
 * - Purpose selection (AI analysis, sandbox processing, or both)
 * - Upload progress tracking
 * - Attachment preview and deletion
 */

import { useState, useRef, useCallback, memo } from 'react';
import { Button, Progress, Select, message, Tag, Tooltip } from 'antd';
import { 
  Paperclip, 
  X, 
  File, 
  Image, 
  FileText, 
  FileCode,
  FileSpreadsheet,
  FileArchive,
  Upload,
  AlertCircle,
  CheckCircle,
} from 'lucide-react';
import { 
  attachmentService, 
  type AttachmentResponse,
} from '@/services/attachmentService';
import type { AttachmentPurpose, UploadProgress } from '@/services/attachmentService';

// ==================== Types ====================

export interface PendingAttachment {
  id: string;  // Temporary ID during upload, then real ID
  file: File;
  filename: string;
  mimeType: string;
  sizeBytes: number;
  purpose: AttachmentPurpose;
  status: 'pending' | 'uploading' | 'uploaded' | 'error';
  progress: number;
  error?: string;
  attachment?: AttachmentResponse;  // Set after successful upload
}

/**
 * Simplified type for completed uploads (for InputBar use)
 */
export interface UploadedFile {
  id: string;
  filename: string;
  mimeType: string;
  size: number;
}

interface FileUploaderProps {
  conversationId?: string;  // Optional - will use temp ID if not provided
  projectId?: string;  // Optional - will use temp ID if not provided
  attachments: PendingAttachment[];
  onAttachmentsChange: (attachments: PendingAttachment[]) => void;
  disabled?: boolean;
  maxFiles?: number;
  maxSizeMB?: number;
}

// ==================== Constants ====================

const PURPOSE_OPTIONS = [
  { 
    value: 'llm_context' as AttachmentPurpose, 
    label: 'AI Analysis',
    description: 'Send to AI for understanding (images, documents)',
  },
  { 
    value: 'sandbox_input' as AttachmentPurpose, 
    label: 'Sandbox Processing',
    description: 'Upload to sandbox for tool execution',
  },
  { 
    value: 'both' as AttachmentPurpose, 
    label: 'Both',
    description: 'AI analysis and sandbox processing',
  },
];

const PURPOSE_COLORS: Record<AttachmentPurpose, string> = {
  'llm_context': 'blue',
  'sandbox_input': 'green',
  'both': 'purple',
};

const PURPOSE_LABELS: Record<AttachmentPurpose, string> = {
  'llm_context': 'AI',
  'sandbox_input': 'Sandbox',
  'both': 'Both',
};

// ==================== Helpers ====================

const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
};

const getFileIcon = (mimeType: string, size: number = 18) => {
  if (mimeType.startsWith('image/')) {
    return <Image size={size} className="text-blue-500" />;
  }
  if (mimeType.includes('pdf') || mimeType.includes('document') || mimeType.includes('word')) {
    return <FileText size={size} className="text-red-500" />;
  }
  if (mimeType.includes('spreadsheet') || mimeType.includes('excel') || mimeType === 'text/csv') {
    return <FileSpreadsheet size={size} className="text-green-500" />;
  }
  if (mimeType.includes('zip') || mimeType.includes('archive') || mimeType.includes('tar')) {
    return <FileArchive size={size} className="text-yellow-500" />;
  }
  if (mimeType.startsWith('text/') || mimeType.includes('json') || mimeType.includes('javascript')) {
    return <FileCode size={size} className="text-purple-500" />;
  }
  return <File size={size} className="text-slate-500" />;
};

// ==================== Component ====================

export const FileUploader = memo<FileUploaderProps>(({
  conversationId,
  projectId,
  attachments,
  onAttachmentsChange,
  disabled = false,
  maxFiles = 10,
  maxSizeMB = 100,
}) => {
  const [selectedPurpose, setSelectedPurpose] = useState<AttachmentPurpose>('both');
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Generate temporary ID (wrapped in useCallback to avoid recreation)
  const generateTempId = useCallback(() => `temp-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`, []);

  // Upload a single file
  const uploadFile = useCallback(async (file: File, purpose: AttachmentPurpose) => {
    // Validate file size
    if (file.size > maxSizeMB * 1024 * 1024) {
      message.error(`File "${file.name}" exceeds ${maxSizeMB}MB limit`);
      return;
    }

    // Skip if missing required IDs
    if (!conversationId || !projectId) {
      message.error('Cannot upload: missing conversation or project context');
      return;
    }

    const tempId = generateTempId();
    const newAttachment: PendingAttachment = {
      id: tempId,
      file,
      filename: file.name,
      mimeType: file.type || 'application/octet-stream',
      sizeBytes: file.size,
      purpose,
      status: 'uploading',
      progress: 0,
    };

    // Add to list
    onAttachmentsChange([...attachments, newAttachment]);

    try {
      // Store current attachments for updates (avoid stale closure)
      let currentAttachments = [...attachments, newAttachment];

      // Upload with progress tracking
      const result = await attachmentService.upload(
        conversationId,
        projectId,
        file,
        purpose,
        (progress: UploadProgress) => {
          // Update progress - use direct state update
          currentAttachments = currentAttachments.map((a: PendingAttachment) => 
            a.id === tempId 
              ? { ...a, progress: progress.percentage }
              : a
          );
          onAttachmentsChange(currentAttachments);
        },
      );

      // Update with successful result
      currentAttachments = currentAttachments.map((a: PendingAttachment) =>
        a.id === tempId
          ? { 
              ...a, 
              id: result.id,  // Use real ID
              status: 'uploaded' as const, 
              progress: 100,
              attachment: result,
            }
          : a
      );
      onAttachmentsChange(currentAttachments);

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Upload failed';
      message.error(`Failed to upload "${file.name}": ${errorMessage}`);
      
      // Update with error
      const updatedAttachments = attachments.map((a: PendingAttachment) =>
        a.id === tempId
          ? { ...a, status: 'error' as const, error: errorMessage }
          : a
      );
      onAttachmentsChange(updatedAttachments);
    }
  }, [attachments, conversationId, projectId, maxSizeMB, onAttachmentsChange, generateTempId]);

  // Handle file selection
  const handleFileSelect = useCallback((files: FileList | null) => {
    if (!files || files.length === 0) return;

    // Check max files
    const currentCount = attachments.length;
    const newCount = files.length;
    if (currentCount + newCount > maxFiles) {
      message.warning(`Maximum ${maxFiles} files allowed`);
      return;
    }

    // Upload each file
    Array.from(files).forEach((file) => {
      uploadFile(file, selectedPurpose);
    });
  }, [attachments.length, maxFiles, selectedPurpose, uploadFile]);

  // Handle input change
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    handleFileSelect(e.target.files);
    // Reset input to allow re-selecting same file
    e.target.value = '';
  }, [handleFileSelect]);

  // Handle drag events
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled) {
      setIsDragging(true);
    }
  }, [disabled]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    
    if (!disabled) {
      handleFileSelect(e.dataTransfer.files);
    }
  }, [disabled, handleFileSelect]);

  // Remove attachment
  const removeAttachment = useCallback((id: string) => {
    const attachment = attachments.find((a) => a.id === id);
    
    // If uploaded, delete from server
    if (attachment?.status === 'uploaded' && attachment.attachment) {
      attachmentService.delete(attachment.attachment.id).catch(() => {
        // Ignore delete errors
      });
    }

    onAttachmentsChange(attachments.filter((a) => a.id !== id));
  }, [attachments, onAttachmentsChange]);

  // Retry failed upload
  const retryUpload = useCallback((attachment: PendingAttachment) => {
    removeAttachment(attachment.id);
    uploadFile(attachment.file, attachment.purpose);
  }, [removeAttachment, uploadFile]);

  // Check if all uploads are complete
  const allUploadsComplete = attachments.every((a) => a.status !== 'uploading');
  const hasErrors = attachments.some((a) => a.status === 'error');

  return (
    <div className="file-uploader">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        onChange={handleInputChange}
        className="hidden"
        disabled={disabled}
      />

      {/* Attachment List */}
      {attachments.length > 0 && (
        <div 
          className={`
            mb-2 p-2 rounded-lg border transition-colors
            ${isDragging 
              ? 'border-primary border-dashed bg-primary/5' 
              : 'border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50'
            }
          `}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <div className="flex flex-wrap gap-2">
            {attachments.map((attachment) => (
              <div
                key={attachment.id}
                className={`
                  flex items-center gap-2 px-2 py-1.5 rounded-lg
                  ${attachment.status === 'error' 
                    ? 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800' 
                    : 'bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600'
                  }
                `}
              >
                {/* File Icon */}
                {getFileIcon(attachment.mimeType, 16)}

                {/* File Info */}
                <div className="flex flex-col min-w-0">
                  <span className="text-xs font-medium truncate max-w-[120px]">
                    {attachment.filename}
                  </span>
                  <span className="text-[10px] text-slate-400">
                    {formatFileSize(attachment.sizeBytes)}
                  </span>
                </div>

                {/* Purpose Tag */}
                <Tag 
                  color={PURPOSE_COLORS[attachment.purpose]} 
                  className="text-[10px] px-1 py-0 leading-tight"
                >
                  {PURPOSE_LABELS[attachment.purpose]}
                </Tag>

                {/* Status Indicator */}
                {attachment.status === 'uploading' && (
                  <div className="w-12">
                    <Progress
                      percent={attachment.progress}
                      size="small"
                      showInfo={false}
                      strokeWidth={3}
                    />
                  </div>
                )}

                {attachment.status === 'uploaded' && (
                  <CheckCircle size={14} className="text-green-500" />
                )}

                {attachment.status === 'error' && (
                  <Tooltip title={attachment.error}>
                    <AlertCircle size={14} className="text-red-500 cursor-help" />
                  </Tooltip>
                )}

                {/* Actions */}
                {attachment.status === 'error' && (
                  <Button
                    type="text"
                    size="small"
                    className="p-0 h-auto text-blue-500 text-xs"
                    onClick={() => retryUpload(attachment)}
                  >
                    Retry
                  </Button>
                )}

                <Button
                  type="text"
                  size="small"
                  icon={<X size={12} />}
                  onClick={() => removeAttachment(attachment.id)}
                  disabled={attachment.status === 'uploading'}
                  className="p-0 h-auto text-slate-400 hover:text-slate-600"
                />
              </div>
            ))}
          </div>

          {/* Drop Zone Indicator */}
          {isDragging && (
            <div className="mt-2 p-4 border-2 border-dashed border-primary rounded-lg text-center">
              <Upload size={24} className="mx-auto mb-1 text-primary" />
              <span className="text-sm text-primary">Drop files here</span>
            </div>
          )}
        </div>
      )}

      {/* Upload Controls */}
      <div className="flex items-center gap-2">
        <Tooltip title="Attach files">
          <Button
            type="text"
            size="small"
            icon={<Paperclip size={16} />}
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || attachments.length >= maxFiles}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
          />
        </Tooltip>

        <Select
          size="small"
          value={selectedPurpose}
          onChange={setSelectedPurpose}
          options={PURPOSE_OPTIONS.map((opt) => ({
            value: opt.value,
            label: (
              <Tooltip title={opt.description} placement="right">
                <span>{opt.label}</span>
              </Tooltip>
            ),
          }))}
          className="w-28"
          disabled={disabled}
          popupMatchSelectWidth={false}
        />

        {/* File count indicator */}
        {attachments.length > 0 && (
          <span className="text-xs text-slate-400">
            {attachments.length}/{maxFiles} files
            {!allUploadsComplete && ' (uploading...)'}
            {hasErrors && (
              <span className="text-red-500 ml-1">
                ({attachments.filter((a) => a.status === 'error').length} failed)
              </span>
            )}
          </span>
        )}
      </div>
    </div>
  );
});

FileUploader.displayName = 'FileUploader';

export default FileUploader;
