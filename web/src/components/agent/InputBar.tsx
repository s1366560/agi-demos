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
import { usePendingPromptStore, usePendingPrompts } from '@/stores/pendingPromptStore';
import { useVoiceCallStore } from '@/stores/voiceCallStore';

import type { FileMetadata } from '@/services/sandboxUploadService';

import { useFrameCapture } from '@/hooks/rtc/useFrameCapture';
import { useActiveModelCapabilities } from '@/hooks/useActiveModelCapabilities';
import { useConversationParticipants } from '@/hooks/useConversationParticipants';
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
import { MentionPicker } from './MentionPicker';
import { QueuedPromptStrip } from './QueuedPromptStrip';
import { SlashCommandDropdown } from './SlashCommandDropdown';

import type { AgentRunMode } from './run/agentRunViewModel';

interface InputBarProps {
  onSend: (
    content: string,
    fileMetadata?: FileMetadata[],
    forcedSkillName?: string,
    forcedSubAgentName?: string,
    imageAttachments?: string[],
    mentions?: string[]
  ) => void;
  onAbort: () => void;
  isStreaming: boolean;
  disabled?: boolean | undefined;
  projectId?: string | undefined;
  conversationId?: string | undefined;
  onTogglePlanMode?: (() => void) | undefined;
  isPlanMode?: boolean | undefined;
  runMode?: AgentRunMode | undefined;
  onRunModeChange?: ((mode: AgentRunMode) => void) | undefined;
  activeAgentId?: string | undefined;
  onAgentSelect?: ((agentId: string) => void) | undefined;
  ref?: React.Ref<HTMLTextAreaElement>;
}

interface WritableRef<T> {
  current: T | null;
}

const assignRef = <T,>(ref: React.Ref<T> | undefined, value: T | null): void => {
  if (!ref) return;
  if (typeof ref === 'function') {
    ref(value);
    return;
  }
  (ref as WritableRef<T>).current = value;
};

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
    runMode,
    onRunModeChange,
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
        assignRef(ref, node);
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
        void useVoiceCallStore.getState().endCall();
      } else {
        if (!activeConversationId) {
          console.warn('[InputBar] Cannot start voice call without an active conversation');
          return;
        }
        if (!projectId) {
          console.warn('[InputBar] Cannot start voice call without a projectId');
          return;
        }
        void useVoiceCallStore.getState().startCall(activeConversationId, projectId);
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

    // Pending-prompt queue: while streaming, Enter queues the message instead
    // of sending. The head of the queue auto-dispatches once streaming ends.
    const queueConvId = activeConversationId ?? conversationId ?? null;
    const queue = usePendingPrompts(queueConvId ?? undefined);
    const enqueuePrompt = usePendingPromptStore((s) => s.enqueue);
    const shiftPrompt = usePendingPromptStore((s) => s.shift);
    const canQueue = isStreaming && !disabled && content.trim().length > 0 && Boolean(queueConvId);

    const clearInputContent = useCallback(() => {
      setContent('');
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }, []);

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
    } = useSlashCommand({ onSend, onInputClear: clearInputContent });

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

    // Shared-mode conversations render MentionPicker (roster-backed)
    // instead of MentionPopover (project-wide subagent search). See
    // files/p3-autonomous-ui-plan.md / f-mention-picker.
    const { roster: mentionRoster } = useConversationParticipants(conversationId ?? null);
    const isSharedMode =
      mentionRoster?.effective_mode === 'multi_agent_shared' ||
      mentionRoster?.effective_mode === 'autonomous';

    // --- Textarea resize ---
    const resizeTextarea = useCallback((target: HTMLTextAreaElement) => {
      target.style.height = 'auto';
      const minHeight = 32;
      const containerHeight = target.parentElement?.clientHeight ?? 400;
      const nextHeight = Math.max(minHeight, Math.min(target.scrollHeight, containerHeight));
      target.style.height = `${String(nextHeight)}px`;
    }, []);

    // --- Send ---
    const handleSend = useCallback(() => {
      // Streaming + text in the box → queue instead of sending. File
      // attachments are not supported in the queue (v1); they stay in the
      // composer until the next manual send.
      if (
        isStreaming &&
        !disabled &&
        queueConvId &&
        content.trim().length > 0 &&
        uploadedAttachments.length === 0
      ) {
        enqueuePrompt(queueConvId, {
          text: content.trim(),
          skillName: selectedSkill?.name,
          subAgentName: selectedSubAgent || undefined,
        });
        clearInputContent();
        resetSlash();
        resetMention();
        return;
      }
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
        imageAttachments,
        isSharedMode && selectedSubAgent ? [selectedSubAgent] : undefined
      );
      clearInputContent();
      resetSlash();
      resetMention();
      clearAll();
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
      isSharedMode,
      isCameraOn,
      captureFrame,
      resetSlash,
      resetMention,
      clearInputContent,
      queueConvId,
      enqueuePrompt,
    ]);

    // Auto-dispatch the head of the queue when streaming ends.
    useEffect(() => {
      if (isStreaming || disabled || !queueConvId || queue.length === 0) return;
      const head = shiftPrompt(queueConvId);
      if (!head) return;
      onSend(head.text, undefined, head.skillName, head.subAgentName, undefined);
    }, [isStreaming, disabled, queueConvId, queue.length, shiftPrompt, onSend]);

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
          (!isStreaming || canQueue)
        ) {
          e.preventDefault();
          handleSend();
        }
      },
      [handleMentionKeyDown, handleSlashKeyDown, handleSend, disabled, isStreaming, canQueue]
    );

    // --- Input ---
    const handleInput = useCallback(
      (e: React.FormEvent<HTMLTextAreaElement>) => {
        const target = e.currentTarget;
        resizeTextarea(target);
        const value = target.value;
        setContent(value);

        if (processSlashInput(value)) return;

        const cursorPos = target.selectionStart || value.length;
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
      <div className="h-full min-w-0 flex flex-col p-2 sm:p-4">
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
          aria-label={t('agent.inputBar.attachFiles', 'Attach files (or drag & drop)')}
          title={t('agent.inputBar.attachFiles', 'Attach files (or drag & drop)')}
          data-testid="chat-file-input"
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
            flex-1 flex flex-col min-h-0 min-w-0 rounded-md border relative
            bg-white dark:bg-slate-800
            transition-[border-color,box-shadow] duration-200 ease-out
            ${
              isDragging
                ? 'border-primary/55 ring-2 ring-primary/15 shadow-[0_1px_5px_rgba(0,112,243,0.08)]'
                : isFocused
                  ? 'border-primary/25 shadow-[0_1px_4px_rgba(0,112,243,0.045)] ring-2 ring-primary/5'
                  : 'border-slate-200/45 dark:border-slate-700/45 shadow-[0_1px_3px_rgba(15,23,42,0.035)] dark:shadow-[0_1px_3px_rgba(0,0,0,0.12)]'
            }
            ${disabled ? 'opacity-60 pointer-events-none' : ''}
          `}
        >
          {/* Drag overlay */}
          {isDragging && (
            <div className="absolute inset-0 z-20 rounded-md bg-primary/5 dark:bg-primary/10 flex items-center justify-center pointer-events-none">
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
            <div className="px-3 pt-3 sm:px-4 flex-shrink-0">
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

          {/* Queued prompts (compose-ahead while streaming) */}
          <div className="flex-shrink-0">
            <QueuedPromptStrip
              conversationId={queueConvId ?? undefined}
              isStreaming={isStreaming}
            />
          </div>

          {/* Text Area */}
          <div
            data-testid="chat-input-body"
            className="relative flex min-h-0 min-w-0 flex-1 px-3 py-2 sm:px-4 overflow-visible"
          >
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
                visible={mentionVisible && !isSharedMode}
                onSelect={handleMentionSelect}
                onClose={() => {
                  setMentionVisible(false);
                  setMentionQuery('');
                }}
                selectedIndex={mentionSelectedIndex}
                onSelectedIndexChange={setMentionSelectedIndex}
              />
            )}
            {isSharedMode && conversationId && (
              <MentionPicker
                conversationId={conversationId}
                query={mentionQuery}
                open={mentionVisible}
                onMentionSelected={(agentId) => {
                  handleMentionSelect({
                    id: agentId,
                    name: agentId,
                    type: 'participant',
                  });
                }}
                onDismiss={() => {
                  setMentionVisible(false);
                  setMentionQuery('');
                }}
              />
            )}
            <div
              data-testid="chat-input-surface"
              className="
                flex h-full min-h-11 w-full min-w-0 flex-wrap content-start items-start gap-1.5 rounded px-2 py-1.5
                bg-slate-50/70 dark:bg-slate-900/40
                transition-colors
              "
            >
              {selectedSkill && (
                <div className="inline-flex max-w-full shrink-0 items-center gap-1 rounded border border-primary/20 bg-primary/5 px-2 py-1 text-xs font-medium text-primary dark:border-primary/30 dark:bg-primary/10">
                  <Zap size={12} />
                  <span className="max-w-[12rem] truncate">/{selectedSkill.name}</span>
                  <button
                    type="button"
                    onClick={handleRemoveSkill}
                    aria-label={t('agent.inputBar.removeSelectedSkill', {
                      name: selectedSkill.name,
                      defaultValue: 'Remove /{{name}} skill',
                    })}
                    title={t('agent.inputBar.removeSelectedSkill', {
                      name: selectedSkill.name,
                      defaultValue: 'Remove /{{name}} skill',
                    })}
                    className="-mr-0.5 rounded p-0.5 transition-colors duration-150 hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                  >
                    <X size={10} />
                  </button>
                </div>
              )}
              {selectedSubAgent && (
                <div className="inline-flex max-w-full shrink-0 items-center gap-1 rounded border border-purple-500/20 bg-purple-500/5 px-2 py-1 text-xs font-medium text-purple-600 dark:border-purple-500/30 dark:bg-purple-500/10 dark:text-purple-400">
                  <Workflow size={12} />
                  <span className="max-w-[10rem] truncate">@{selectedSubAgent}</span>
                  <button
                    type="button"
                    onClick={handleRemoveSubAgent}
                    aria-label={t('agent.inputBar.removeSelectedSubAgent', {
                      name: selectedSubAgent,
                      defaultValue: 'Remove @{{name}} subagent',
                    })}
                    title={t('agent.inputBar.removeSelectedSubAgent', {
                      name: selectedSubAgent,
                      defaultValue: 'Remove @{{name}} subagent',
                    })}
                    className="-mr-0.5 rounded p-0.5 transition-colors duration-150 hover:bg-purple-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                  >
                    <X size={10} />
                  </button>
                </div>
              )}
              <textarea
                id="agent-message-input"
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
                  h-auto min-w-40 flex-1 bg-transparent px-1 py-1
                  text-sm leading-relaxed text-slate-800 dark:text-slate-100
                  placeholder:text-slate-400 dark:placeholder:text-slate-500
                  focus:outline-none
                  overflow-y-auto overflow-x-hidden
                  break-words font-sans
                  scrollbar-thin scrollbar-thumb-slate-300 dark:scrollbar-thumb-slate-600
                  scrollbar-track-transparent scrollbar-w-1.5
                  hover:scrollbar-thumb-slate-400 dark:hover:scrollbar-thumb-slate-500
                "
                style={{
                  resize: 'none',
                  minHeight: '32px',
                  maxHeight: '100%',
                }}
              />
            </div>
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
            runMode={runMode}
            onRunModeChange={onRunModeChange}
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
}>(({ file, onRemove, onRetry }) => {
  const { t } = useTranslation();
  const retryLabel = t('agent.inputBar.retryAttachmentUpload', {
    filename: file.filename,
    defaultValue: 'Retry upload for {{filename}}',
  });
  const removeLabel = t('agent.inputBar.removeAttachment', {
    filename: file.filename,
    defaultValue: 'Remove {{filename}} attachment',
  });

  return (
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
            aria-label={retryLabel}
            title={retryLabel}
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
        aria-label={removeLabel}
        title={removeLabel}
        className="p-0.5 hover:bg-slate-200 dark:hover:bg-slate-600 rounded transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ml-0.5 disabled:opacity-30"
      >
        <X size={12} className="text-slate-400 hover:text-slate-600" />
      </button>
    </div>
  );
});

AttachmentChip.displayName = 'AttachmentChip';

export default InputBar;
