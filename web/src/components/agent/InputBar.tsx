/**
 * InputBar - Chat input bar with inline file upload
 *
 * Features:
 * - Glass-morphism design with auto-resizing textarea
 * - Drag-and-drop file upload on the entire input card
 * - Paperclip button opens native file picker directly
 * - Inline attachment chips with progress / error states
 * - Plan mode toggle
 */

import { useState, useRef, useCallback, useEffect, memo, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { Popover } from 'antd';
import {
  Send,
  Square,
  Paperclip,
  X,
  FileText,
  Image as ImageIcon,
  File,
  Upload,
  AlertCircle,
  RotateCw,
  Zap,
  BookOpen,
  Mic,
  MicOff,
  Phone,
  PhoneOff,
  MessageSquare,
  Terminal,
  ListChecks,
  Workflow,
  Bot,
  CheckCircle2,
} from 'lucide-react';

import { useAgentV3Store } from '@/stores/agentV3';
import { useSubAgentStore } from '@/stores/subagent';
import { useVoiceCallStore } from '@/stores/voiceCallStore';

import type { MentionItem } from '@/services/mentionService';
import type { FileMetadata } from '@/services/sandboxUploadService';

import { useFrameCapture } from '@/hooks/rtc/useFrameCapture';
import { useActiveModelCapabilities } from '@/hooks/useActiveModelCapabilities';
import { useVoiceTranscribe } from '@/hooks/useVoiceTranscribe';

import { LazyButton, LazyTooltip } from '@/components/ui/lazyAntd';

import { AgentSwitcher } from './AgentSwitcher';
import { LlmOverridePopover } from './chat/LlmOverridePopover';
import { MentionPopover } from './chat/MentionPopover';
import { ModelSwitchPopover } from './chat/ModelSwitchPopover';
import { PromptTemplateLibrary } from './chat/PromptTemplateLibrary';
import { VoiceCallPanel } from './chat/VoiceCallPanel';
import { VoiceWaveform } from './chat/VoiceWaveform';
import { useFileUpload, type PendingAttachment } from './FileUploader';
import { SlashCommandDropdown } from './SlashCommandDropdown';

import type { SkillResponse, SlashItem } from '@/types/agent';

import type { MentionPopoverHandle } from './chat/MentionPopover';
import type { SlashCommandDropdownHandle } from './SlashCommandDropdown';

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
  onTogglePlanMode?: (() => void) | undefined;
  isPlanMode?: boolean | undefined;
  activeAgentId?: string | undefined;
  onAgentSelect?: ((agentId: string) => void) | undefined;
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
    onTogglePlanMode,
    isPlanMode,
    activeAgentId,
    onAgentSelect,
  }) => {
    const { t } = useTranslation();
    const [content, setContent] = useState('');
    const [inputMode, setInputMode] = useState<'chat' | 'command'>('chat');
    const [isFocused, setIsFocused] = useState(false);
    const [isDragging, setIsDragging] = useState(false);
    const [selectedSkill, setSelectedSkill] = useState<SkillResponse | null>(null);
    const [selectedSubAgent, setSelectedSubAgent] = useState<string | null>(null);
    const [slashDropdownVisible, setSlashDropdownVisible] = useState(false);
    const [slashQuery, setSlashQuery] = useState('');
    const [slashSelectedIndex, setSlashSelectedIndex] = useState(0);
    const [templateLibraryVisible, setTemplateLibraryVisible] = useState(false);
    const [subagentPickerOpen, setSubagentPickerOpen] = useState(false);
    const [mentionVisible, setMentionVisible] = useState(false);
    const [mentionQuery, setMentionQuery] = useState('');
    const [mentionSelectedIndex, setMentionSelectedIndex] = useState(0);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const mentionPopoverRef = useRef<MentionPopoverHandle>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const slashDropdownRef = useRef<SlashCommandDropdownHandle>(null);
    const dragCounter = useRef(0);
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

    const subagents = useSubAgentStore((s) => s.subagents);
    const listSubAgents = useSubAgentStore((s) => s.listSubAgents);

    useEffect(() => {
      void listSubAgents({ enabled_only: true });
    }, [listSubAgents]);

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

    const resizeTextarea = useCallback((target: HTMLTextAreaElement) => {
      target.style.height = 'auto';
      const minHeight = 56;
      const containerHeight = target.parentElement?.clientHeight ?? 400;
      const nextHeight = Math.max(minHeight, Math.min(target.scrollHeight, containerHeight));
      target.style.height = `${String(nextHeight)}px`;
    }, []);

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
      const messageContent =
        inputMode === 'command' ? `[command] ${content.trim()}` : content.trim();
      // Auto-capture video frame when camera is active
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
      setSelectedSkill(null);
      setSelectedSubAgent(null);
      setSlashDropdownVisible(false);
      setMentionVisible(false);
      setMentionQuery('');
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
      inputMode,
      isCameraOn,
      captureFrame,
    ]);

    const handleTemplateSelect = useCallback((prompt: string) => {
      setContent(prompt);
      setTemplateLibraryVisible(false);
      setTimeout(() => textareaRef.current?.focus(), 50);
    }, []);

    const handleMentionSelect = useCallback(
      (item: MentionItem) => {
        const textarea = textareaRef.current;
        if (!textarea) return;

        const cursorPos = textarea.selectionStart;
        const textBefore = content.slice(0, cursorPos);
        const textAfter = content.slice(cursorPos);

        // Find the "@" trigger position before cursor
        const atIndex = textBefore.lastIndexOf('@');
        if (atIndex === -1) return;

        // Special handling for SubAgents: select as "force delegate" instead of inserting text
        if (item.type === 'subagent') {
          setSelectedSubAgent(item.name);
          setMentionVisible(false);
          setMentionQuery('');

          // Remove the trigger text (e.g. "@sub")
          const before = content.slice(0, atIndex);
          const newContent = before + textAfter;
          setContent(newContent);

          // Restore cursor position (at the deleted point)
          setTimeout(() => {
            textarea.focus();
            textarea.setSelectionRange(atIndex, atIndex);
          }, 50);
          return;
        }

        const before = content.slice(0, atIndex);
        const replacement = `@${item.name} `;
        const newContent = before + replacement + textAfter;

        setContent(newContent);
        setMentionVisible(false);
        setMentionQuery('');

        // Restore cursor position after the inserted mention
        const newCursor = atIndex + replacement.length;
        setTimeout(() => {
          textarea.focus();
          textarea.setSelectionRange(newCursor, newCursor);
        }, 0);
      },
      [content]
    );

    const handleSlashSelect = useCallback(
      (item: SlashItem) => {
        if (item.kind === 'skill') {
          setSelectedSkill(item.data);
          setSlashDropdownVisible(false);
          setContent('');
          setSlashQuery('');
          // Focus textarea for typing the message
          textareaRef.current?.focus();
        } else {
          setSlashDropdownVisible(false);
          setSlashQuery('');
          const cmdText = `/${item.data.name}`;
          onSend(cmdText);
          setContent('');
        }
      },
      [onSend]
    );

    const handleRemoveSkill = useCallback(() => {
      setSelectedSkill(null);
    }, []);

    const handleRemoveSubAgent = useCallback(() => {
      setSelectedSubAgent(null);
    }, []);

    const handleKeyDown = useCallback(
      (e: React.KeyboardEvent) => {
        // Mention dropdown keyboard navigation
        if (mentionVisible) {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setMentionSelectedIndex((prev) => prev + 1);
            return;
          }
          if (e.key === 'ArrowUp') {
            e.preventDefault();
            setMentionSelectedIndex((prev) => Math.max(0, prev - 1));
            return;
          }
          if (e.key === 'Enter' || e.key === 'Tab') {
            e.preventDefault();
            const item = mentionPopoverRef.current?.getSelectedItem();
            if (item) {
              handleMentionSelect(item);
            }
            return;
          }
          if (e.key === 'Escape') {
            e.preventDefault();
            setMentionVisible(false);
            setMentionQuery('');
            return;
          }
        }

        // Slash-command keyboard navigation
        if (slashDropdownVisible) {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setSlashSelectedIndex((prev) => prev + 1);
            return;
          }
          if (e.key === 'ArrowUp') {
            e.preventDefault();
            setSlashSelectedIndex((prev) => Math.max(0, prev - 1));
            return;
          }
          if (e.key === 'Enter') {
            e.preventDefault();
            const item = slashDropdownRef.current?.getSelectedItem();
            if (item) {
              handleSlashSelect(item);
            }
            return;
          }
          if (e.key === 'Escape') {
            e.preventDefault();
            setSlashDropdownVisible(false);
            setContent('');
            return;
          }
        }

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
      [
        handleSend,
        handleMentionSelect,
        handleSlashSelect,
        disabled,
        isStreaming,
        slashDropdownVisible,
        mentionVisible,
      ]
    );

    const handleInput = useCallback(
      (e: React.FormEvent<HTMLTextAreaElement>) => {
        const target = e.currentTarget;
        resizeTextarea(target);
        const value = target.value;
        setContent(value);

        // Slash-command detection: "/" at start of input
        if (value.startsWith('/') && !selectedSkill) {
          const query = value.slice(1);
          // Only show dropdown for single-word slash query (no spaces = still typing skill name)
          if (!query.includes(' ')) {
            setSlashQuery(query);
            setSlashDropdownVisible(true);
            setSlashSelectedIndex(0);
            return;
          }
        }

        // Close slash dropdown if conditions no longer met
        if (slashDropdownVisible) {
          setSlashDropdownVisible(false);
        }

        // @-mention detection: find "@" before cursor followed by non-space chars
        // We allow mentions even if subagent is selected (e.g. to mention entities)
        // But the MentionPopover should probably filter out subagents if one is already selected?
        // For now, let's just allow it. If they select another subagent, it replaces the current one.
        const cursorPos = target.selectionStart;
        const textBefore = value.slice(0, cursorPos);
        const mentionMatch = textBefore.match(/@([^\s@]*)$/);
        if (mentionMatch) {
          setMentionQuery(mentionMatch[1] ?? '');
          setMentionVisible(true);
          setMentionSelectedIndex(0);
        } else if (mentionVisible) {
          setMentionVisible(false);
          setMentionQuery('');
        }
      },
      [selectedSkill, slashDropdownVisible, mentionVisible, resizeTextarea]
    );

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

    // --- Paste files (Ctrl/Cmd+V with images or files) ---
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
          files.forEach((f) => dt.items.add(f));
          addFiles(dt.files);
        }
      },
      [disabled, addFiles, capabilities.supportsAttachment]
    );

    // --- Drag-and-drop on the entire input card ---
    const handleDragEnter = useCallback(
      (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        dragCounter.current += 1;
        if (
          !disabled &&
          capabilities.supportsAttachment &&
          e.dataTransfer.types.includes('Files')
        ) {
          setIsDragging(true);
        }
      },
      [disabled, capabilities.supportsAttachment]
    );

    const handleDragOver = useCallback((e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
    }, []);

    const handleDragLeave = useCallback((e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter.current -= 1;
      if (dragCounter.current <= 0) {
        dragCounter.current = 0;
        setIsDragging(false);
      }
    }, []);

    const handleDrop = useCallback(
      (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        dragCounter.current = 0;
        setIsDragging(false);
        if (!disabled && capabilities.supportsAttachment && e.dataTransfer.files.length > 0) {
          addFiles(e.dataTransfer.files);
        }
      },
      [disabled, addFiles, capabilities.supportsAttachment]
    );

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

    const subagentPickerContent = useMemo(
      () => (
        <div className="w-56 max-h-64 overflow-y-auto py-1">
          {subagents.length === 0 ? (
            <div className="px-3 py-4 text-center text-xs text-slate-400">
              No SubAgents available
            </div>
          ) : (
            subagents.map((sa) => (
              <button
                key={sa.id}
                type="button"
                onClick={() => {
                  if (selectedSubAgent === sa.name) {
                    setSelectedSubAgent(null);
                  } else {
                    setSelectedSubAgent(sa.name);
                  }
                  setSubagentPickerOpen(false);
                }}
                className={`w-full text-left px-3 py-2 text-sm hover:bg-slate-100 dark:hover:bg-slate-700/50 transition-colors flex items-center gap-2 ${
                  selectedSubAgent === sa.name
                    ? 'bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-300'
                    : 'text-slate-700 dark:text-slate-300'
                }`}
              >
                <Bot
                  size={14}
                  className={selectedSubAgent === sa.name ? 'text-purple-500' : 'text-slate-400'}
                />
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{sa.display_name || sa.name}</div>
                  {sa.trigger?.description && (
                    <div className="text-[10px] text-slate-400 truncate">
                      {sa.trigger.description}
                    </div>
                  )}
                </div>
                {selectedSubAgent === sa.name && (
                  <CheckCircle2 size={14} className="text-purple-500 shrink-0" />
                )}
              </button>
            ))
          )}
        </div>
      ),
      [subagents, selectedSubAgent]
    );

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
        <div
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
                  className="ml-0.5 p-0.5 hover:bg-primary/10 rounded-full transition-colors"
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
                  className="ml-0.5 p-0.5 hover:bg-purple-500/10 rounded-full transition-colors"
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
              ref={textareaRef}
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
              aria-label={
                inputMode === 'command'
                  ? t('agent.inputBar.commandPlaceholder', 'Enter a command...')
                  : t('agent.inputBar.placeholder', "Ask me anything, or type '/' for commands...")
              }
              placeholder={
                inputMode === 'command'
                  ? t('agent.inputBar.commandPlaceholder', 'Enter a command...')
                  : t('agent.inputBar.placeholder', "Ask me anything, or type '/' for commands...")
              }
              rows={1}
              data-testid="chat-input"
              className={`
                w-full h-auto rounded-lg px-3 py-2
                bg-slate-50/80 dark:bg-slate-900/50
                text-slate-800 dark:text-slate-100
                placeholder:text-slate-400 dark:placeholder:text-slate-500
                focus:outline-none text-sm leading-relaxed
                overflow-y-auto overflow-x-hidden
                break-words
                scrollbar-thin scrollbar-thumb-slate-300 dark:scrollbar-thumb-slate-600
                scrollbar-track-transparent scrollbar-w-1.5
                hover:scrollbar-thumb-slate-400 dark:hover:scrollbar-thumb-slate-500
                ${inputMode === 'command' ? 'font-mono' : 'font-sans'}
              `}
              style={{
                // Auto-resize with content, scroll when exceeds parent container
                resize: 'none',
                minHeight: '56px',
                maxHeight: '100%',
              }}
            />
          </div>

          {/* Toolbar */}
          <div className="flex-shrink-0 px-3 pt-2 pb-2.5 flex items-center gap-1">
            {/* Left Actions */}
            <div className="flex items-center">
              <LazyTooltip
                title={
                  capabilities.supportsAttachment
                    ? t('agent.inputBar.attachFiles', 'Attach files (or drag & drop)')
                    : t(
                        'agent.inputBar.attachNotSupported',
                        'Current model does not support file attachments'
                      )
                }
              >
                <LazyButton
                  type="text"
                  size="small"
                  icon={<Paperclip size={18} />}
                  onClick={() => fileInputRef.current?.click()}
                  disabled={!capabilities.supportsAttachment}
                  aria-label={t('agent.inputBar.attachFiles', 'Attach files (or drag & drop)')}
                  className={`
                    text-slate-500 hover:text-slate-700 dark:hover:text-slate-300
                    hover:bg-slate-100 dark:hover:bg-slate-700/50
                    rounded-lg h-8 w-8 flex items-center justify-center
                    ${attachments.length > 0 ? 'text-primary' : ''}
                    ${!capabilities.supportsAttachment ? 'opacity-40 cursor-not-allowed' : ''}
                  `}
                />
              </LazyTooltip>

              <LazyTooltip title={t('agent.inputBar.templates', 'Prompt templates')}>
                <LazyButton
                  data-tour="prompt-templates"
                  type="text"
                  size="small"
                  icon={<BookOpen size={18} />}
                  onClick={() => {
                    setTemplateLibraryVisible((v) => !v);
                  }}
                  aria-label={t('agent.inputBar.templates', 'Prompt templates')}
                  className={`
                    text-slate-500 hover:text-slate-700 dark:hover:text-slate-300
                    hover:bg-slate-100 dark:hover:bg-slate-700/50
                    rounded-lg h-8 w-8 flex items-center justify-center
                    ${templateLibraryVisible ? 'text-primary bg-primary/5' : ''}
                  `}
                />
              </LazyTooltip>

              <LazyTooltip
                title={
                  isListening
                    ? t('agent.inputBar.stopVoice', 'Stop voice input')
                    : t('agent.inputBar.startVoice', 'Voice input')
                }
              >
                <LazyButton
                  type="text"
                  size="small"
                  icon={isListening ? <MicOff size={18} /> : <Mic size={18} />}
                  onClick={toggleVoiceInput}
                  disabled={voiceCallStatus !== 'idle'}
                  aria-label={
                    isListening
                      ? t('agent.inputBar.stopVoice', 'Stop voice input')
                      : t('agent.inputBar.startVoice', 'Voice input')
                  }
                  className={`
                    rounded-lg h-8 w-8 flex items-center justify-center transition-colors
                    ${
                      isListening
                        ? 'text-red-500 bg-red-50 dark:bg-red-900/20'
                        : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50'
                    }
                  `}
                />
              </LazyTooltip>
              <VoiceWaveform active={isListening} />

              <LazyTooltip
                title={voiceCallStatus !== 'idle' ? 'End voice call' : 'Start voice call'}
              >
                <LazyButton
                  type="text"
                  size="small"
                  icon={voiceCallStatus !== 'idle' ? <PhoneOff size={18} /> : <Phone size={18} />}
                  onClick={handleVoiceCall}
                  disabled={!!(isStreaming || disabled || isListening)}
                  aria-label={voiceCallStatus !== 'idle' ? 'End voice call' : 'Start voice call'}
                  className={`
                    rounded-lg h-8 w-8 flex items-center justify-center transition-colors
                    ${
                      voiceCallStatus !== 'idle'
                        ? 'text-green-500 bg-green-50 dark:bg-green-900/20 animate-pulse motion-reduce:animate-none'
                        : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50'
                    }
                  `}
                />
              </LazyTooltip>

              <LlmOverridePopover
                conversationId={activeConversationId}
                disabled={!!(isStreaming || disabled)}
                capabilities={capabilities}
              />

              <ModelSwitchPopover
                conversationId={activeConversationId}
                projectId={projectId}
                disabled={!!(isStreaming || disabled)}
              />

              {onAgentSelect && (
                <AgentSwitcher
                  activeAgentId={activeAgentId}
                  onSelect={onAgentSelect}
                  className="h-8"
                />
              )}

              <Popover
                content={subagentPickerContent}
                trigger="click"
                open={subagentPickerOpen}
                onOpenChange={setSubagentPickerOpen}
                placement="topLeft"
                arrow={false}
                styles={{ content: { padding: 0 } }}
              >
                <LazyTooltip
                  title={selectedSubAgent ? `SubAgent: ${selectedSubAgent}` : 'Choose SubAgent'}
                >
                  <button
                    type="button"
                    disabled={!!(isStreaming || disabled)}
                    aria-label={
                      selectedSubAgent ? `SubAgent: ${selectedSubAgent}` : 'Choose SubAgent'
                    }
                    className={`
                      flex items-center justify-center h-8 w-8 rounded-lg transition-colors
                      ${
                        selectedSubAgent
                          ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 hover:bg-purple-200 dark:hover:bg-purple-900/50'
                          : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50 disabled:opacity-40'
                      }
                    `}
                  >
                    <Bot size={16} />
                  </button>
                </LazyTooltip>
              </Popover>

              <div className="w-px h-4 bg-slate-200 dark:bg-slate-700 mx-1.5" />

              {onTogglePlanMode && (
                <LazyTooltip
                  title={
                    isPlanMode
                      ? t('agent.inputBar.exitPlanMode', 'Exit Plan Mode (Shift+Tab)')
                      : t('agent.inputBar.enterPlanMode', 'Enter Plan Mode (Shift+Tab)')
                  }
                >
                  <button
                    type="button"
                    onClick={onTogglePlanMode}
                    disabled={isStreaming}
                    aria-label={
                      isPlanMode
                        ? t('agent.inputBar.exitPlanMode', 'Exit Plan Mode (Shift+Tab)')
                        : t('agent.inputBar.enterPlanMode', 'Enter Plan Mode (Shift+Tab)')
                    }
                    className={`
                      flex items-center justify-center h-8 w-8 rounded-lg transition-colors
                      ${
                        isPlanMode
                          ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 hover:bg-blue-200 dark:hover:bg-blue-900/50'
                          : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50 disabled:opacity-40'
                      }
                    `}
                  >
                    <ListChecks size={16} />
                  </button>
                </LazyTooltip>
              )}

              <LazyTooltip
                title={
                  inputMode === 'command'
                    ? t('agent.inputBar.commandMode', 'Command')
                    : t('agent.inputBar.chatMode', 'Chat')
                }
              >
                <button
                  type="button"
                  onClick={() => {
                    setInputMode(inputMode === 'chat' ? 'command' : 'chat');
                  }}
                  aria-label={t('agent.inputBar.modeToggle', 'Toggle input mode')}
                  className={`
                    flex items-center justify-center h-8 w-8 rounded-lg transition-colors
                    ${
                      inputMode === 'command'
                        ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400'
                        : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50'
                    }
                  `}
                  title={t('agent.inputBar.modeToggle', 'Toggle input mode')}
                >
                  {inputMode === 'chat' ? <MessageSquare size={16} /> : <Terminal size={16} />}
                </button>
              </LazyTooltip>
            </div>

            {/* Spacer */}
            <div className="flex-1" />

            {/* Right Actions */}
            <div className="flex items-center gap-2">
              {charCount > 0 && (
                <span
                  className={`text-xs font-medium transition-colors ${charCount > 4000 ? 'text-amber-500' : 'text-slate-400'}`}
                >
                  {charCount.toLocaleString()}
                </span>
              )}

              {isStreaming ? (
                <LazyButton
                  type="primary"
                  danger
                  size="small"
                  icon={<Square size={14} className="fill-current" />}
                  onClick={onAbort}
                  className="rounded-xl flex items-center gap-1.5 h-8 px-3 shadow-sm"
                >
                  {t('agent.inputBar.stop', 'Stop')}
                </LazyButton>
              ) : (
                <LazyButton
                  type="primary"
                  size="small"
                  icon={<Send size={14} />}
                  onClick={handleSend}
                  disabled={!canSend}
                  aria-label={t('agent.inputBar.send', 'Send message')}
                  className={`
                    rounded-xl flex items-center gap-1.5 h-8 px-3
                    bg-gradient-to-r from-primary to-primary-600
                    hover:from-primary-600 hover:to-primary-700
                    shadow-md shadow-primary/20
                    disabled:opacity-40 disabled:shadow-none disabled:cursor-not-allowed
                    transition-colors duration-200
                  `}
                >
                  {t('agent.inputBar.send', 'Send')}
                </LazyButton>
              )}
            </div>
          </div>

          {/* Prompt Template Library popover */}
          <PromptTemplateLibrary
            visible={templateLibraryVisible}
            onSelect={handleTemplateSelect}
            onClose={() => {
              setTemplateLibraryVisible(false);
            }}
          />
          {voiceCallStatus !== 'idle' && <VoiceCallPanel onClose={handleVoiceCall} />}
        </div>
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
          className="p-0.5 hover:bg-red-100 dark:hover:bg-red-900/30 rounded transition-colors"
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
      className="p-0.5 hover:bg-slate-200 dark:hover:bg-slate-600 rounded transition-colors ml-0.5 disabled:opacity-30"
    >
      <X size={12} className="text-slate-400 hover:text-slate-600" />
    </button>
  </div>
));

AttachmentChip.displayName = 'AttachmentChip';

export default InputBar;
