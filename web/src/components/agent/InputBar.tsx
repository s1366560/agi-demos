/**
 * InputBar - Modern floating input bar with file attachment support
 *
 * Features:
 * - Glass-morphism design
 * - Auto-resizing textarea
 * - File attachment preview
 * - Plan mode toggle
 * - Modern iconography
 */

import { useState, useRef, useCallback, memo } from 'react';

import {
  Send,
  Square,
  Paperclip,
  Mic,
  Wand2,
  X,
  FileText,
  Image as ImageIcon,
  File,
  Sparkles,
} from 'lucide-react';

import { LazyButton, LazyTooltip, LazyBadge, LazyPopover } from '@/components/ui/lazyAntd';

import { FileUploader, type PendingAttachment } from './FileUploader';

interface InputBarProps {
  onSend: (content: string, attachmentIds?: string[]) => void;
  onAbort: () => void;
  isStreaming: boolean;
  isPlanMode: boolean;
  onTogglePlanMode: () => void;
  disabled?: boolean;
  conversationId?: string;
  projectId?: string;
}

// Get icon for file type
const getFileIcon = (mimeType: string) => {
  if (mimeType.startsWith('image/')) return <ImageIcon size={14} className="text-emerald-500" />;
  if (mimeType.includes('pdf') || mimeType.includes('document'))
    return <FileText size={14} className="text-red-500" />;
  return <File size={14} className="text-blue-500" />;
};

// Format file size
const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

// Memoized InputBar to prevent unnecessary re-renders
export const InputBar = memo<InputBarProps>(
  ({
    onSend,
    onAbort,
    isStreaming,
    isPlanMode,
    onTogglePlanMode,
    disabled,
    conversationId,
    projectId,
  }) => {
    const [content, setContent] = useState('');
    const [isFocused, setIsFocused] = useState(false);
    const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
    const [showUploader, setShowUploader] = useState(false);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    // Get completed attachment IDs
    const uploadedAttachments = attachments.filter((a) => a.status === 'uploaded' && a.attachment);
    const pendingCount = attachments.filter((a) => a.status === 'uploading').length;

    // Combine disabled and isStreaming for send button state
    const canSend =
      !disabled &&
      !isStreaming &&
      (content.trim().length > 0 || uploadedAttachments.length > 0) &&
      pendingCount === 0;

    const handleSend = useCallback(() => {
      if (
        (!content.trim() && uploadedAttachments.length === 0) ||
        isStreaming ||
        disabled ||
        pendingCount > 0
      )
        return;
      const attachmentIds = uploadedAttachments
        .filter((a) => a.attachment !== undefined)
        .map((a) => a.attachment?.id ?? '');
      onSend(content.trim(), attachmentIds.length > 0 ? attachmentIds : undefined);
      setContent('');
      setAttachments([]);
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }, [content, uploadedAttachments, isStreaming, disabled, pendingCount, onSend]);

    const handleKeyDown = useCallback(
      (e: React.KeyboardEvent) => {
        if (
          e.key === 'Enter' &&
          !e.shiftKey &&
          !e.nativeEvent.isComposing &&
          !disabled &&
          !isStreaming
        ) {
          e.preventDefault();
          handleSend();
        }
      },
      [handleSend, disabled, isStreaming]
    );

    const handleInput = useCallback((e: React.FormEvent<HTMLTextAreaElement>) => {
      const target = e.currentTarget;
      target.style.height = 'auto';
      // Minimum height for 3 lines (approx 72px + padding)
      const minHeight = 72;
      const newHeight = Math.max(minHeight, Math.min(target.scrollHeight, 400));
      target.style.height = `${newHeight}px`;
      setContent(target.value);
    }, []);

    const removeAttachment = useCallback((id: string) => {
      setAttachments((prev) => prev.filter((a) => a.id !== id));
    }, []);

    const charCount = content.length;
    const showCharCount = charCount > 0;

    return (
      <div className="h-full flex flex-col p-4">
        {/* Main input card - Glass morphism style */}
        <div
          className={`
        flex-1 flex flex-col min-h-0 rounded-2xl border 
        bg-white/90 dark:bg-slate-800/90
        backdrop-blur-sm
        transition-all duration-300 ease-out
        shadow-lg
        ${
          isFocused
            ? 'border-primary/40 shadow-primary/10 ring-2 ring-primary/10'
            : 'border-slate-200/60 dark:border-slate-700/60 shadow-slate-200/50 dark:shadow-black/20'
        }
        ${disabled ? 'opacity-60 pointer-events-none' : ''}
      `}
        >
          {/* Plan Mode Badge */}
          {isPlanMode && (
            <div className="px-4 pt-3 flex-shrink-0">
              <div className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/30 dark:to-indigo-900/20 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800/50 rounded-full text-xs font-medium">
                <Sparkles size={12} />
                Plan Mode Active
              </div>
            </div>
          )}

          {/* Attachments Preview */}
          {attachments.length > 0 && (
            <div className="px-4 pt-3 flex-shrink-0">
              <div className="flex flex-wrap gap-2">
                {attachments.map((file) => (
                  <div
                    key={file.id}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs border ${
                      file.status === 'error'
                        ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800/50'
                        : 'bg-slate-50 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600'
                    }`}
                  >
                    {getFileIcon(file.mimeType)}
                    <span className="max-w-[120px] truncate text-slate-700 dark:text-slate-300">
                      {file.filename}
                    </span>
                    <span className="text-slate-400">{formatSize(file.sizeBytes)}</span>
                    {file.status === 'uploading' && (
                      <span className="text-blue-500 font-medium">{file.progress}%</span>
                    )}
                    {file.status === 'error' && (
                      <span className="text-red-500 text-xs font-medium">Failed</span>
                    )}
                    <button
                      type="button"
                      onClick={() => removeAttachment(file.id)}
                      className="p-0.5 hover:bg-slate-200 dark:hover:bg-slate-600 rounded transition-colors ml-1"
                    >
                      <X size={12} className="text-slate-400 hover:text-slate-600" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Text Area - fills available space, minimum 3 rows */}
          <div className="flex-1 min-h-0 px-4 py-3">
            <textarea
              ref={textareaRef}
              value={content}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              onFocus={() => setIsFocused(true)}
              onBlur={() => setIsFocused(false)}
              placeholder={
                isPlanMode
                  ? 'Describe what you want to plan in detail...'
                  : "Ask me anything, or type '/' for commands..."
              }
              rows={3}
              className="
              w-full h-full resize-none bg-transparent
              text-slate-800 dark:text-slate-100
              placeholder:text-slate-400 dark:placeholder:text-slate-500
              focus:outline-none
              text-[15px] leading-relaxed
              min-h-[72px]
            "
            />
          </div>

          {/* Toolbar */}
          <div className="flex-shrink-0 px-3 pb-3 flex items-center justify-between">
            {/* Left Actions */}
            <div className="flex items-center gap-1">
              <LazyPopover
                content={
                  <FileUploader
                    conversationId={conversationId}
                    projectId={projectId}
                    attachments={attachments}
                    onAttachmentsChange={setAttachments}
                    maxFiles={10}
                    maxSizeMB={100}
                  />
                }
                trigger="click"
                open={showUploader}
                onOpenChange={setShowUploader}
                placement="topLeft"
                overlayClassName="file-uploader-popover"
              >
                <LazyTooltip title="Attach file">
                  <LazyButton
                    type="text"
                    size="small"
                    icon={
                      <LazyBadge count={attachments.length} size="small" offset={[-2, 2]}>
                        <Paperclip size={18} />
                      </LazyBadge>
                    }
                    className={`
                    text-slate-500 hover:text-slate-700 dark:hover:text-slate-300
                    hover:bg-slate-100 dark:hover:bg-slate-700/50
                    rounded-lg h-9 w-9 flex items-center justify-center
                    ${attachments.length > 0 ? 'text-primary' : ''}
                  `}
                  />
                </LazyTooltip>
              </LazyPopover>

              <LazyTooltip title="Voice input">
                <LazyButton
                  type="text"
                  size="small"
                  icon={<Mic size={18} />}
                  className="
                  text-slate-500 hover:text-slate-700 dark:hover:text-slate-300
                  hover:bg-slate-100 dark:hover:bg-slate-700/50
                  rounded-lg h-9 w-9 flex items-center justify-center
                "
                />
              </LazyTooltip>

              <div className="w-px h-5 bg-slate-200 dark:bg-slate-700 mx-1" />

              <LazyTooltip title={isPlanMode ? 'Exit Plan Mode' : 'Enter Plan Mode'}>
                <LazyButton
                  type="text"
                  size="small"
                  onClick={onTogglePlanMode}
                  className={`
                  flex items-center gap-1.5 h-9 px-3 rounded-lg transition-all
                  ${
                    isPlanMode
                      ? 'text-blue-600 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800/50'
                      : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50'
                  }
                `}
                >
                  <Wand2 size={16} />
                  <span className="text-sm font-medium">Plan</span>
                </LazyButton>
              </LazyTooltip>
            </div>

            {/* Right Actions */}
            <div className="flex items-center gap-3">
              {/* Character Count */}
              {showCharCount && (
                <span
                  className={`
                text-xs transition-colors font-medium
                ${charCount > 4000 ? 'text-amber-500' : 'text-slate-400'}
              `}
                >
                  {charCount.toLocaleString()}
                </span>
              )}

              {/* Send/Stop Button */}
              {isStreaming ? (
                <LazyButton
                  type="primary"
                  danger
                  size="middle"
                  icon={<Square size={14} className="fill-current" />}
                  onClick={onAbort}
                  className="rounded-xl flex items-center gap-2 h-9 px-4 shadow-md"
                >
                  Stop
                </LazyButton>
              ) : (
                <LazyButton
                  type="primary"
                  size="middle"
                  icon={<Send size={14} />}
                  onClick={handleSend}
                  disabled={!canSend}
                  className={`
                  rounded-xl flex items-center gap-2 h-9 px-4
                  bg-gradient-to-r from-primary to-primary-600
                  hover:from-primary-600 hover:to-primary-700
                  shadow-lg shadow-primary/25
                  disabled:opacity-40 disabled:shadow-none disabled:cursor-not-allowed
                  transition-all duration-200
                `}
                >
                  Send
                </LazyButton>
              )}
            </div>
          </div>
        </div>

      </div>
    );
  }
);

InputBar.displayName = 'InputBar';

export default InputBar;
