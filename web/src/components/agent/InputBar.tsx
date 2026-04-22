import { useState, useRef, useCallback, useEffect, memo } from 'react';

import { useTranslation } from 'react-i18next';

import {
  X,
  FileText,
  Image as ImageIcon,
  File,
  Upload,
  AlertCircle,
  RotateCw,
  Zap,
  ListChecks,
  Workflow,
} from 'lucide-react';

import { useAgentV3Store } from '@/stores/agentV3';
import { useVoiceCallStore } from '@/stores/voiceCallStore';

import type { FileMetadata } from '@/services/sandboxUploadService';

import { useFrameCapture } from '@/hooks/rtc/useFrameCapture';
import { useActiveModelCapabilities } from '@/hooks/useActiveModelCapabilities';
import { useVoiceTranscribe } from '@/hooks/useVoiceTranscribe';

import { LazyTooltip } from '@/components/ui/lazyAntd';

import { MentionPopover } from './chat/MentionPopover';
import { PromptTemplateLibrary } from './chat/PromptTemplateLibrary';
import { VoiceCallPanel } from './chat/VoiceCallPanel';
import { useFileUpload, type PendingAttachment } from './FileUploader';
import { useDragAndDrop } from './hooks/useDragAndDrop';
import { useMentionDetection } from './hooks/useMentionDetection';
import { useSlashCommand } from './hooks/useSlashCommand';
import { InputToolbar } from './InputToolbar';
import { SlashCommandDropdown } from './SlashCommandDropdown';

interface InputBarProps {
  onSend: (
    content: string,
    fileMetadata?: FileMetadata[],
    forcedSkillName?: string,
    forcedSubAgentName?: string,
    imageAttachments?: string[]
  ) => void;
  onAbort: () => void;
  isStreaming: boolean;
  disabled?: boolean | undefined;
  projectId?: string | undefined;
  conversationId?: string | undefined;
  onTogglePlanMode?: (() => void) | undefined;
  isPlanMode?: boolean | undefined;
  activeAgentId?: string | undefined;
  onAgentSelect?: ((agentId: string) => void) | undefined;
  ref?: React.Ref<HTMLTextAreaElement>;
}

const getFileIcon = (mimeType: string) => {
  if (mimeType.startsWith('image/')) return <ImageIcon size={14} className="text-emerald-500" />;
  if (mimeType.includes('pdf') || mimeType.includes('document'))
    return <FileText size={14} className="text-red-500" />;
  return <File size={14} className="text-blue-500" />;
};

const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

export const InputBar = memo<InputBarProps>(
  ({
    onSend,
    onAbort,
    isStreaming,
    disabled,
    projectId,
    conversationId,
    onTogglePlanMode,
    isPlanMode,
    activeAgentId,
    onAgentSelect,
    ref,
  }) => {
    const { t } = useTranslation();
    const [content, setContent] = useState('');
    const [isFocused, setIsFocused] = useState(false);
    const [templateLibraryVisible, setTemplateLibraryVisible] = useState(false);

    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const mergedRef = useCallback(
      (node: HTMLTextAreaElement | null) => {
        textareaRef.current = node;
        if (typeof ref === 'function') {
          ref(node);
        } else if (ref) {
          (ref as React.MutableRefObject<HTMLTextAreaElement | null>).current = node;
        }
      },
      [ref]
    );

    const fileInputRef = useRef<HTMLInputElement>(null);
    const contentRef = useRef(content);
    useEffect(() => {
      contentRef.current = content;
    }, [content]);

    const activeConversationId = useAgentV3Store((state) => state.activeConversationId);
    const activeModelOverride = useAgentV3Store((state) => {
      const convId = state.activeConversationId;
      if (!convId) return null;
      const convState = state.conversationStates.get(convId);
      const ctx = convState?.appModelContext as Record<string, unknown> | null;
      const raw = ctx?.llm_model_override;
      if (typeof raw !== 'string') return null;
      const trimmed = raw.trim();
      return trimmed.length > 0 ? trimmed : null;
    });

    const voiceCallStatus = useVoiceCallStore((state) => state.status);
    const isCameraOn = useVoiceCallStore((state) => state.isCameraOn);

    const { captureFrame } = useFrameCapture();
    const handleVoiceCall = useCallback(() => {
      if (voiceCallStatus !== 'idle') {
        useVoiceCallStore.getState().endCall();
      } else {
        if (!activeConversationId) {
          console.warn('[InputBar] Cannot start voice call without an active conversation');
          return;
        }
        if (!projectId) {
          console.warn('[InputBar] Cannot start voice call without a projectId');
          return;
        }
        useVoiceCallStore.getState().startCall(activeConversationId, projectId);
      }
    }, [voiceCallStatus, activeConversationId, projectId]);

    const capabilities = useActiveModelCapabilities(activeModelOverride);

    // --- Voice transcription ---
    const voicePrefixRef = useRef('');
    const { isListening, toggle: rawToggleVoice } = useVoiceTranscribe({
      projectId,
      conversationId: activeConversationId ?? undefined,
      onInterim: useCallback((text: string) => {
        setContent(voicePrefixRef.current + text);
      }, []),
      onFinal: useCallback((text: string) => {
        const prefix = voicePrefixRef.current;
        voicePrefixRef.current = prefix + text;
        setContent(prefix + text);
      }, []),
    });
    const toggleVoiceInput = useCallback(async () => {
      if (!isListening) {
        voicePrefixRef.current = contentRef.current;
      }
      await rawToggleVoice();
    }, [isListening, rawToggleVoice]);

    // --- File upload ---
    const { attachments, addFiles, removeAttachment, retryAttachment, clearAll } = useFileUpload({
      projectId,
      maxFiles: 10,
      maxSizeMB: 100,
    });

    const uploadedAttachments = attachments.filter(
      (a) => a.status === 'uploaded' && a.fileMetadata
    );
    const pendingCount = attachments.filter((a) => a.status === 'uploading').length;

    const canSend =
      !disabled &&
      !isStreaming &&
      (content.trim().length > 0 || uploadedAttachments.length > 0) &&
      pendingCount === 0;

    // --- Extracted hooks ---
    const {
      slashDropdownVisible,
      slashQuery,
      slashSelectedIndex,
      setSlashSelectedIndex,
      handleSlashSelect,
      processSlashInput,
      handleSlashKeyDown,
      setSlashDropdownVisible,
      selectedSkill,
      handleRemoveSkill,
      slashDropdownRef,
      resetSlash,
    } = useSlashCommand({ onSend });

    const {
      mentionVisible,
      mentionQuery,
      mentionSelectedIndex,
      setMentionSelectedIndex,
      handleMentionSelect,
      processMentionInput,
      handleMentionKeyDown,
      setMentionVisible,
      setMentionQuery,
      mentionPopoverRef,
      selectedSubAgent,
      handleRemoveSubAgent,
      resetMention,
    } = useMentionDetection({ content, setContent, textareaRef });

    const { isDragging, handleDragEnter, handleDragOver, handleDragLeave, handleDrop } =
      useDragAndDrop({
        disabled: Boolean(disabled),
        supportsAttachment: capabilities.supportsAttachment,
        addFiles,
      });

    // --- Textarea resize ---
    const resizeTextarea = useCallback((target: HTMLTextAreaElement) => {
      target.style.height = 'auto';
      const minHeight = 56;
      const containerHeight = target.parentElement?.clientHeight ?? 400;
      const nextHeight = Math.max(minHeight, Math.min(target.scrollHeight, containerHeight));
      target.style.height = `${String(nextHeight)}px`;
    }, []);

    // --- Send ---
    const handleSend = useCallback(() => {
      if (
        (!content.trim() && uploadedAttachments.length === 0) ||
        isStreaming ||
        disabled ||
        pendingCount > 0
      )
        return;
      const fileMetadataList = uploadedAttachments.flatMap((a) =>
        a.fileMetadata !== undefined ? [a.fileMetadata] : []
      );
      const messageContent = content.trim();

      let imageAttachments: string[] | undefined;
      if (isCameraOn) {
        const frame = captureFrame('local-video-container');
        if (frame) {
          imageAttachments = [frame.dataUrl];
        }
      }
      onSend(
        messageContent,
        fileMetadataList.length > 0 ? fileMetadataList : undefined,
        selectedSkill?.name,
        selectedSubAgent || undefined,
        imageAttachments
      );
      setContent('');
      resetSlash();
      resetMention();
      clearAll();
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }, [
      content,
      uploadedAttachments,
      isStreaming,
      disabled,
      pendingCount,
      onSend,
      clearAll,
      selectedSkill,
      selectedSubAgent,
      isCameraOn,
      captureFrame,
      resetSlash,
      resetMention,
    ]);

    // --- Template select ---
    const handleTemplateSelect = useCallback((prompt: string) => {
      setContent(prompt);
      setTemplateLibraryVisible(false);
      setTimeout(() => textareaRef.current?.focus(), 50);
    }, []);

    // --- Keyboard ---
    const handleKeyDown = useCallback(
      (e: React.KeyboardEvent) => {
        if (handleMentionKeyDown(e)) return;
        if (handleSlashKeyDown(e)) return;

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
      [handleMentionKeyDown, handleSlashKeyDown, handleSend, disabled, isStreaming]
    );

    // --- Input ---
    const handleInput = useCallback(
      (e: React.FormEvent<HTMLTextAreaElement>) => {
        const target = e.currentTarget;
        resizeTextarea(target);
        const value = target.value;
        setContent(value);

        if (processSlashInput(value)) return;

        const cursorPos = target.selectionStart;
        processMentionInput(value, cursorPos);
      },
      [resizeTextarea, processSlashInput, processMentionInput]
    );

    // --- Resize effects ---
    // biome-ignore lint/correctness/useExhaustiveDependencies: content triggers textarea resize
    useEffect(() => {
      if (textareaRef.current) {
        resizeTextarea(textareaRef.current);
      }
    }, [content, resizeTextarea]);

    useEffect(() => {
      const textarea = textareaRef.current;
      const container = textarea?.parentElement;
      if (!textarea || !container || typeof ResizeObserver === 'undefined') {
        return;
      }

      const observer = new ResizeObserver(() => {
        resizeTextarea(textarea);
      });
      observer.observe(container);

      return () => {
        observer.disconnect();
      };
    }, [resizeTextarea]);

    // --- Paste ---
    const handlePaste = useCallback(
      (e: React.ClipboardEvent) => {
        if (disabled) return;
        const items = e.clipboardData.items;

        const files: File[] = [];
        for (const item of items) {
          if (item.kind === 'file') {
            const file = item.getAsFile();
            if (file) files.push(file);
          }
        }

        if (files.length > 0 && capabilities.supportsAttachment) {
          e.preventDefault();
          const dt = new DataTransfer();
          for (const f of files) {
            dt.items.add(f);
          }
          addFiles(dt.files);
        }
      },
      [disabled, addFiles, capabilities.supportsAttachment]
    );

    // --- File input change ---
    const handleFileInputChange = useCallback(
      (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files.length > 0) {
          addFiles(e.target.files);
        }
        e.target.value = '';
      },
      [addFiles]
    );

    const charCount = content.length;

    return (
      <div className="h-full flex flex-col p-4">
        {/* Plan Mode indicator */}
        {isPlanMode && (
          <div className="mb-2 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800/50 text-blue-700 dark:text-blue-300 text-sm">
            <ListChecks size={14} />
            <span className="font-medium">{t('agent.inputBar.planModeLabel', 'Plan Mode')}</span>
            <span className="text-blue-500 dark:text-blue-400 text-xs">
              {t(
                'agent.inputBar.planModeHint',
                'Read-only analysis. Agent will plan without making changes.'
              )}
            </span>
          </div>
        )}

        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileInputChange}
          className="hidden"
          disabled={disabled || !capabilities.supportsAttachment}
        />

        {/* Main input card */}
        {/* biome-ignore lint/a11y/noStaticElementInteractions: drag-drop target has no semantic interactive role */}
        <section
          data-tour="input-bar"
          onDragEnter={handleDragEnter}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`
            flex-1 flex flex-col min-h-0 rounded-xl border relative
            bg-white dark:bg-slate-800
            transition-shadow duration-200 ease-out shadow-lg
            ${
              isDragging
                ? 'border-primary/60 ring-2 ring-primary/20 shadow-primary/15'
                : isFocused
                  ? 'border-primary/40 shadow-primary/10 ring-2 ring-primary/10'
                  : 'border-slate-200/60 dark:border-slate-700/60 shadow-slate-200/50 dark:shadow-black/20'
            }
            ${disabled ? 'opacity-60 pointer-events-none' : ''}
          `}
        >
          {/* Drag overlay */}
          {isDragging && (
            <div className="absolute inset-0 z-20 rounded-xl bg-primary/5 dark:bg-primary/10 flex items-center justify-center pointer-events-none">
              <div className="flex flex-col items-center gap-2 text-primary">
                <Upload size={28} strokeWidth={1.5} />
                <span className="text-sm font-medium">
                  {t('agent.inputBar.dropToUpload', 'Drop files to upload')}
                </span>
              </div>
            </div>
          )}

          {/* Inline Attachment Chips */}
          {attachments.length > 0 && (
            <div className="px-4 pt-3 flex-shrink-0">
              <div className="flex flex-wrap gap-2">
                {attachments.map((file) => (
                  <AttachmentChip
                    key={file.id}
                    file={file}
                    onRemove={removeAttachment}
                    onRetry={retryAttachment}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Selected Skill Badge */}
          {selectedSkill && (
            <div className="px-4 pt-3 flex-shrink-0">
              <div className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-primary/5 to-primary/10 dark:from-primary/10 dark:to-primary/15 text-primary border border-primary/20 dark:border-primary/30 rounded-full text-xs font-medium">
                <Zap size={12} />
                <span>/{selectedSkill.name}</span>
                <button
                  type="button"
                  onClick={handleRemoveSkill}
                  className="ml-0.5 p-0.5 hover:bg-primary/10 rounded-full transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                >
                  <X size={10} />
                </button>
              </div>
            </div>
          )}

          {/* Selected SubAgent Badge */}
          {selectedSubAgent && (
            <div className="px-4 pt-3 flex-shrink-0">
              <div className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-purple-500/5 to-purple-500/10 dark:from-purple-500/10 dark:to-purple-500/15 text-purple-600 dark:text-purple-400 border border-purple-500/20 dark:border-purple-500/30 rounded-full text-xs font-medium">
                <Workflow size={12} />
                <span>@{selectedSubAgent}</span>
                <button
                  type="button"
                  onClick={handleRemoveSubAgent}
                  className="ml-0.5 p-0.5 hover:bg-purple-500/10 rounded-full transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                >
                  <X size={10} />
                </button>
              </div>
            </div>
          )}

          {/* Text Area */}
          <div className="flex-1 min-h-0 px-4 py-3 relative overflow-visible">
            <SlashCommandDropdown
              ref={slashDropdownRef}
              query={slashQuery}
              visible={slashDropdownVisible}
              onSelect={handleSlashSelect}
              onClose={() => {
                setSlashDropdownVisible(false);
              }}
              selectedIndex={slashSelectedIndex}
              onSelectedIndexChange={setSlashSelectedIndex}
            />
            {projectId && (
              <MentionPopover
                ref={mentionPopoverRef}
                query={mentionQuery}
                projectId={projectId}
                conversationId={conversationId ?? null}
                visible={mentionVisible}
                onSelect={handleMentionSelect}
                onClose={() => {
                  setMentionVisible(false);
                  setMentionQuery('');
                }}
                selectedIndex={mentionSelectedIndex}
                onSelectedIndexChange={setMentionSelectedIndex}
              />
            )}
            <textarea
              ref={mergedRef}
              value={content}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              onFocus={() => {
                setIsFocused(true);
              }}
              onBlur={() => {
                setIsFocused(false);
              }}
              aria-label={t(
                'agent.inputBar.placeholder',
                "Ask me anything, or type '/' for commands..."
              )}
              placeholder={t(
                'agent.inputBar.placeholder',
                "Ask me anything, or type '/' for commands..."
              )}
              rows={1}
              data-testid="chat-input"
              dir="auto"
              autoCapitalize="sentences"
              className="
                w-full h-auto rounded-lg px-3 py-2
                bg-slate-50/80 dark:bg-slate-900/50
                text-slate-800 dark:text-slate-100
                placeholder:text-slate-400 dark:placeholder:text-slate-500
                focus:outline-none text-sm leading-relaxed
                overflow-y-auto overflow-x-hidden
                break-words font-sans
                scrollbar-thin scrollbar-thumb-slate-300 dark:scrollbar-thumb-slate-600
                scrollbar-track-transparent scrollbar-w-1.5
                hover:scrollbar-thumb-slate-400 dark:hover:scrollbar-thumb-slate-500
              "
              style={{
                resize: 'none',
                minHeight: '56px',
                maxHeight: '100%',
              }}
            />
          </div>

          {/* Toolbar */}
          <InputToolbar
            fileInputRef={fileInputRef}
            attachments={attachments}
            capabilities={capabilities}
            templateLibraryVisible={templateLibraryVisible}
            setTemplateLibraryVisible={setTemplateLibraryVisible}
            isListening={isListening}
            toggleVoiceInput={toggleVoiceInput}
            voiceCallStatus={voiceCallStatus}
            handleVoiceCall={handleVoiceCall}
            activeConversationId={activeConversationId}
            projectId={projectId}
            isStreaming={isStreaming}
            disabled={disabled}
            onTogglePlanMode={onTogglePlanMode}
            isPlanMode={isPlanMode}
            onAgentSelect={onAgentSelect}
            activeAgentId={activeAgentId}
            charCount={charCount}
            canSend={canSend}
            handleSend={handleSend}
            onAbort={onAbort}
          />

          {/* Prompt Template Library popover */}
          <PromptTemplateLibrary
            visible={templateLibraryVisible}
            onSelect={handleTemplateSelect}
            onClose={() => {
              setTemplateLibraryVisible(false);
            }}
          />
          {voiceCallStatus !== 'idle' && <VoiceCallPanel onClose={handleVoiceCall} />}
        </section>
      </div>
    );
  }
);

InputBar.displayName = 'InputBar';

// --- Attachment Chip ---

const AttachmentChip = memo<{
  file: PendingAttachment;
  onRemove: (id: string) => void;
  onRetry: (id: string) => void;
}>(({ file, onRemove, onRetry }) => (
  <div
    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs border transition-colors ${
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
      <>
        <LazyTooltip title={file.error}>
          <AlertCircle size={13} className="text-red-500 cursor-help" />
        </LazyTooltip>
        <button
          type="button"
          onClick={() => {
            onRetry(file.id);
          }}
          className="p-0.5 hover:bg-red-100 dark:hover:bg-red-900/30 rounded transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
        >
          <RotateCw size={12} className="text-red-500" />
        </button>
      </>
    )}
    <button
      type="button"
      onClick={() => {
        onRemove(file.id);
      }}
      disabled={file.status === 'uploading'}
      className="p-0.5 hover:bg-slate-200 dark:hover:bg-slate-600 rounded transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ml-0.5 disabled:opacity-30"
    >
      <X size={12} className="text-slate-400 hover:text-slate-600" />
    </button>
  </div>
));

AttachmentChip.displayName = 'AttachmentChip';

export default InputBar;
