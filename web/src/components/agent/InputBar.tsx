/**
 * InputBar - Modern floating input bar with file attachment support
 */

import { useState, useRef, useCallback, memo } from 'react';
import { Button, Tooltip, Badge, Popover } from 'antd';
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
} from 'lucide-react';
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
  if (mimeType.startsWith('image/')) return <ImageIcon size={14} className="text-green-500" />;
  if (mimeType.includes('pdf') || mimeType.includes('document')) return <FileText size={14} className="text-red-500" />;
  return <File size={14} className="text-blue-500" />;
};

// Format file size
const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

// Memoized InputBar to prevent unnecessary re-renders (rerender-memo)
export const InputBar = memo<InputBarProps>(({
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
  const uploadedAttachments = attachments.filter(a => a.status === 'uploaded' && a.attachment);
  const pendingCount = attachments.filter(a => a.status === 'uploading').length;
  
  // Combine disabled and isStreaming for send button state
  const canSend = !disabled && !isStreaming && (content.trim().length > 0 || uploadedAttachments.length > 0) && pendingCount === 0;
  
  const handleSend = useCallback(() => {
    if ((!content.trim() && uploadedAttachments.length === 0) || isStreaming || disabled || pendingCount > 0) return;
    const attachmentIds = uploadedAttachments
      .filter(a => a.attachment !== undefined)
      .map(a => a.attachment?.id ?? '');
    onSend(content.trim(), attachmentIds.length > 0 ? attachmentIds : undefined);
    setContent('');
    setAttachments([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [content, uploadedAttachments, isStreaming, disabled, pendingCount, onSend]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && !disabled && !isStreaming) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend, disabled, isStreaming]);

  const handleInput = useCallback((e: React.FormEvent<HTMLTextAreaElement>) => {
    const target = e.currentTarget;
    target.style.height = 'auto';
    target.style.height = `${Math.min(target.scrollHeight, 400)}px`;
    setContent(target.value);
  }, []);

  const removeAttachment = useCallback((id: string) => {
    setAttachments(prev => prev.filter(a => a.id !== id));
  }, []);

  const charCount = content.length;
  const showCharCount = charCount > 0;

  return (
    <div className="h-full flex flex-col p-3">
      {/* Main input card */}
      <div className={`
        flex-1 flex flex-col min-h-0 rounded-xl border bg-white dark:bg-slate-800
        transition-all duration-200
        ${isFocused 
          ? 'border-primary shadow-lg shadow-primary/10' 
          : 'border-slate-200 dark:border-slate-700 shadow-sm'
        }
        ${disabled ? 'opacity-60 pointer-events-none' : ''}
      `}>
        {/* Plan Mode Badge */}
        {isPlanMode && (
          <div className="px-3 pt-2 flex-shrink-0">
            <Badge className="bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-800 text-xs">
              <span className="flex items-center gap-1">
                <Wand2 size={12} />
                Plan Mode Active
              </span>
            </Badge>
          </div>
        )}

        {/* Attachments Preview */}
        {attachments.length > 0 && (
          <div className="px-3 pt-2 flex-shrink-0">
            <div className="flex flex-wrap gap-2">
              {attachments.map(file => (
                <div
                  key={file.id}
                  className={`flex items-center gap-2 px-2 py-1 rounded-lg text-xs ${
                    file.status === 'error' 
                      ? 'bg-red-50 dark:bg-red-900/20' 
                      : 'bg-slate-100 dark:bg-slate-700'
                  }`}
                >
                  {getFileIcon(file.mimeType)}
                  <span className="max-w-[120px] truncate text-slate-700 dark:text-slate-300">
                    {file.filename}
                  </span>
                  <span className="text-slate-400">
                    {formatSize(file.sizeBytes)}
                  </span>
                  {file.status === 'uploading' && (
                    <span className="text-blue-500">{file.progress}%</span>
                  )}
                  {file.status === 'error' && (
                    <span className="text-red-500 text-xs">Failed</span>
                  )}
                  <button
                    type="button"
                    onClick={() => removeAttachment(file.id)}
                    className="p-0.5 hover:bg-slate-200 dark:hover:bg-slate-600 rounded transition-colors"
                  >
                    <X size={12} className="text-slate-400 hover:text-slate-600" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Text Area - fills available space */}
        <div className="flex-1 min-h-0 px-3 py-2">
          <textarea
            ref={textareaRef}
            value={content}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            placeholder={isPlanMode 
              ? "Describe what you want to plan..." 
              : "Message the AI or type '/' for commands..."
            }
            className="
              w-full h-full resize-none bg-transparent
              text-slate-900 dark:text-slate-100
              placeholder:text-slate-400
              focus:outline-none
              text-sm leading-relaxed
            "
          />
        </div>

        {/* Toolbar */}
        <div className="flex-shrink-0 px-2 pb-2 flex items-center justify-between">
          {/* Left Actions */}
          <div className="flex items-center gap-1">
            <Popover
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
              <Tooltip title="Attach file">
                <Button
                  type="text"
                  size="small"
                  icon={
                    <Badge count={attachments.length} size="small" offset={[-2, 2]}>
                      <Paperclip size={16} />
                    </Badge>
                  }
                  className={`text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 ${attachments.length > 0 ? 'text-primary' : ''}`}
                />
              </Tooltip>
            </Popover>
            <Tooltip title="Voice input">
              <Button
                type="text"
                size="small"
                icon={<Mic size={16} />}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
              />
            </Tooltip>
            <div className="w-px h-4 bg-slate-200 dark:bg-slate-700 mx-1" />
            <Tooltip title={isPlanMode ? "Exit Plan Mode" : "Enter Plan Mode"}>
              <Button
                type="text"
                size="small"
                onClick={onTogglePlanMode}
                className={`
                  flex items-center gap-1
                  ${isPlanMode 
                    ? 'text-blue-600 bg-blue-50 dark:bg-blue-900/20' 
                    : 'text-slate-400 hover:text-slate-600'
                  }
                `}
              >
                <Wand2 size={14} />
                <span className="text-xs font-medium">Plan</span>
              </Button>
            </Tooltip>
          </div>

          {/* Right Actions */}
          <div className="flex items-center gap-2">
            {/* Character Count */}
            {showCharCount && (
              <span className={`
                text-xs transition-colors
                ${charCount > 4000 ? 'text-amber-500' : 'text-slate-400'}
              `}>
                {charCount}
              </span>
            )}

            {/* Send/Stop Button */}
            {isStreaming ? (
              <Button
                type="primary"
                danger
                size="small"
                icon={<Square size={14} />}
                onClick={onAbort}
                className="rounded-lg flex items-center gap-1"
              >
                Stop
              </Button>
            ) : (
              <Button
                type="primary"
                size="small"
                icon={<Send size={14} />}
                onClick={handleSend}
                disabled={!canSend}
                className="
                  rounded-lg flex items-center gap-1
                  bg-primary hover:bg-primary-600
                  disabled:opacity-40 disabled:cursor-not-allowed
                "
              >
                Send
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Footer hint - outside card, below it */}
      <div className="flex-shrink-0 mt-1.5 text-center">
        <p className="text-[10px] text-slate-400 dark:text-slate-500">
          <kbd className="px-1 py-0.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-slate-500 dark:text-slate-400 font-sans">Enter</kbd> to send, <kbd className="px-1 py-0.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-slate-500 dark:text-slate-400 font-sans">Shift + Enter</kbd> for new line
        </p>
      </div>
    </div>
  );
});

InputBar.displayName = 'InputBar';

export default InputBar;
